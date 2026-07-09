import base64
import binascii

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import NoResultFound

from app import document_download_client
from app.clients.document_download import DocumentDownloadError
from app.dao.files_dao import (
    dao_archive_file,
    dao_create_file,
    dao_get_file_by_document_id,
    dao_get_file_by_id,
    dao_get_file_status_by_id_and_template_id,
    dao_get_files_by_template_id,
    dao_update_file,
)
from app.dao.permissions_dao import permission_dao
from app.dao.templates_dao import dao_get_template_by_id
from app.errors import InvalidRequest, register_errors
from app.files.files_schema import (
    guardduty_scan_verdict_callback_schema,
    post_create_file_schema,
)
from app.models import (
    FILE_STATUS_PENDING_VIRUS_SCAN,
    FILE_STATUS_UPLOADED,
    FILE_STATUS_VIRUS_SCAN_FAILED,
    MANAGE_TEMPLATES,
    UPLOAD_DOCUMENT,
    Files,
)
from app.notifications.validators import check_service_has_permission, validate_template_exists
from app.schema_validation import validate
from app.schemas import files_schema

files_blueprint = Blueprint("files", __name__, url_prefix="/templates/<uuid:template_id>/files")
register_errors(files_blueprint)

scan_verdict_callback_blueprint = Blueprint("scan_verdict_callback", __name__, url_prefix="/templates/scan-verdict-callback")
register_errors(scan_verdict_callback_blueprint)

GUARD_DUTY_STATUS_MAP = {
    "NO_THREATS_FOUND": FILE_STATUS_UPLOADED,
    "THREATS_FOUND": FILE_STATUS_VIRUS_SCAN_FAILED,
    "RUNNING": FILE_STATUS_PENDING_VIRUS_SCAN,
    # Leave scan errors terminal so UI can show failure rather than spin forever
    "UNSUPPORTED": FILE_STATUS_VIRUS_SCAN_FAILED,
    "ACCESS_DENIED": FILE_STATUS_VIRUS_SCAN_FAILED,
    "FAILED": FILE_STATUS_VIRUS_SCAN_FAILED,
    "SKIPPED": FILE_STATUS_VIRUS_SCAN_FAILED,
}


@files_blueprint.route("", methods=["POST"])
def create_file(template_id):
    data = request.get_json()
    validate(data, post_create_file_schema)

    user_id = data["created_by"]
    permissions = {p.permission for p in permission_dao.get_permissions_by_user_id(data["created_by"])}

    if MANAGE_TEMPLATES not in permissions:
        raise InvalidRequest(f"User {user_id} does not have {MANAGE_TEMPLATES} permissions.", 403)

    try:
        template = dao_get_template_by_id(template_id)
    except NoResultFound:
        raise InvalidRequest("Template not found", status_code=404)

    service = template.service
    check_service_has_permission(UPLOAD_DOCUMENT, service.permissions)
    validate_template_exists(template_id, service)

    filename = data["name"]
    mime_type = data["mime_type"]
    try:
        file_data = base64.b64decode(data["file_data"])
        uploaded_file = document_download_client.upload_template_attachment(service.id, file_data, filename, mime_type)
    except (binascii.Error, ValueError):
        raise InvalidRequest("file_data is not valid base64", status_code=400)
    except DocumentDownloadError as e:
        raise InvalidRequest(e.message, status_code=e.status_code)

    document_id = uploaded_file["document"]["id"]
    current_app.logger.info(f"Uploaded file to S3 for template {template_id} document_id: {document_id}")

    file = Files(
        template_id=data["template_id"],
        service_id=service.id,
        document_id=document_id,
        type=data["type"],
        name=data["name"],
        mime_type=data["mime_type"],
        file_size=data["file_size"],
        status=FILE_STATUS_PENDING_VIRUS_SCAN,
        created_by_id=data["created_by"],
    )
    dao_create_file(file)

    return jsonify(files_schema.dump(file)), 201


@files_blueprint.route("")
def get_files_by_template_id(template_id):
    files = dao_get_files_by_template_id(template_id)
    data = files_schema.dump(files, many=True)
    return jsonify(data)


@files_blueprint.route("/<uuid:file_id>/status", methods=["GET"])
def get_file_status(template_id, file_id):
    file_status = dao_get_file_status_by_id_and_template_id(file_id, template_id)
    return jsonify({"status": file_status}), 200


@files_blueprint.route("/<uuid:file_id>", methods=["DELETE"])
def delete_file(template_id, file_id):
    fetched_file = dao_get_file_by_id(file_id)

    if fetched_file.template_id != template_id:
        raise InvalidRequest(
            f"Requested file_id {file_id} is not associated with template {template_id}",
            404,
        )

    # Delete from S3 via document-download-api first
    try:
        document_download_client.delete_document(fetched_file.service_id, fetched_file.document_id, "template_attach")
        current_app.logger.info(
            f"Deleted file from S3: document_id {fetched_file.document_id} file_id {file_id} template_id {template_id}"
        )
    except DocumentDownloadError as e:
        current_app.logger.error(f"Failed to delete file from S3 (document_id {fetched_file.document_id}): {e.message}")
        raise InvalidRequest(f"Failed to delete file from storage: {e.message}", status_code=e.status_code)
    except Exception as e:
        current_app.logger.error(f"Unexpected error deleting file from S3 (document_id {fetched_file.document_id}): {str(e)}")
        raise InvalidRequest("Failed to delete file from storage", 500)

    # Only archive in database if S3 deletion succeeded
    dao_archive_file(fetched_file)

    current_app.logger.info(f"Deleted file: {file_id} template_id {template_id}")
    return "", 204


@scan_verdict_callback_blueprint.route("", methods=["POST"])
def update_file_status():
    """Callback endpoints that receives completed scan verdicts from GuardDuty / EventBridge
    and updates the file in the DB with the appropriate scan verdict status.

    The EventBridge connection calls this endpoint when it receives a file scan verdict event
    from GuardDuty. Only events meeting the following criteria will be forwarded to this endpoint:
    1. The scan_status is COMPLETED or FAILED
    2. The scan was on the `*-document-download-scan-files` bucket
    3. The scanned key matches `/template/<service_id>/<document_id>`
    """
    event = request.get_json()
    validate(event, guardduty_scan_verdict_callback_schema)

    parsed = _parse_scan_verdict_payload(event)
    document_id = parsed["document_id"]
    service_id = parsed["service_id"]
    new_status = parsed["new_status"]

    fetched_file = dao_get_file_by_document_id(document_id)
    if str(fetched_file.service_id) != service_id:
        raise InvalidRequest(
            f"Requested document_id {fetched_file.document_id} is not associated with service {service_id}",
            404,
        )

    fetched_file.status = new_status
    dao_update_file(fetched_file)

    current_app.logger.info(
        f"Updated file status to {new_status} for file_id: {fetched_file.id} "
        f"template_id: {fetched_file.template_id} document_id: {fetched_file.document_id} "
    )
    return jsonify(files_schema.dump(fetched_file)), 200


def _parse_scan_verdict_payload(event):
    scan_status = event.get("scan_status")
    scan_result = event.get("scan_result_status")
    object_key = event["object_key"]
    bucket_name = event.get("bucket_name")

    current_app.logger.info(
        f"Received Scan result: bucket={bucket_name} key={object_key}" f" scanStatus={scan_status} scanResult={scan_result}"
    )
    normalized_key = object_key.lstrip("/")
    _, service_id, document_id = normalized_key.split("/", 2)

    if scan_status == "COMPLETED":
        new_status = GUARD_DUTY_STATUS_MAP.get(scan_result, FILE_STATUS_VIRUS_SCAN_FAILED)
    else:
        new_status = GUARD_DUTY_STATUS_MAP.get(scan_status, FILE_STATUS_VIRUS_SCAN_FAILED)

    return {
        "status": "ok",
        "service_id": service_id,
        "document_id": document_id,
        "new_status": new_status,
    }
