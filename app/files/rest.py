import uuid

from flask import Blueprint, current_app, jsonify, request

from app import authenticated_service
from app.dao.files_dao import (
    dao_create_file,
    dao_delete_file,
    dao_get_file_by_id,
    dao_get_files_by_template_id,
    dao_update_file,
)
from app.dao.services_dao import dao_fetch_service_by_id
from app.dao.templates_dao import dao_get_template_by_id
from app.errors import register_errors
from app.files.files_schema import (
    post_create_file_schema,
    post_update_file_status_schema,
)
from app.models import FILE_STATUS_PENDING_VIRUS_SCAN, UPLOAD_DOCUMENT, Files
from app.notifications.validators import check_service_has_permission, validate_template_exists
from app.schema_validation import validate
from app.schemas import files_schema

files_blueprint = Blueprint("files", __name__, url_prefix="/templates/<uuid:template_id>/files")
register_errors(files_blueprint)


@files_blueprint.route("", methods=["POST"])
def create_file(template_id):
    data = request.get_json()
    validate(data, post_create_file_schema)
    template_id = data["template_id"]

    # TODO: Remove temp DB fallback for service when ready to hook up to admin.
    # This is just to enable testing via API calls until admin is hooked up
    template = dao_get_template_by_id(template_id)
    service = (
        authenticated_service if getattr(authenticated_service, "id", False) else dao_fetch_service_by_id(template.service_id)
    )
    check_service_has_permission(UPLOAD_DOCUMENT, service.permissions)
    validate_template_exists(template_id, service)

    # TODO: Uncomment when dd-api has been updated with the correct paths for template file attachments
    # file_data = data["file_data"]
    # try:
    #     uploaded_file = document_download_client.upload_document(service.id, file_data)
    # except DocumentDownloadError as e:
    #     raise InvalidRequest(e.message, status_code=e.status_code)

    # current_app.logger.info(f"Uploaded file to S3 for template {template_id} document_id: {uploaded_file["id"]} ")

    file = Files(
        template_id=data["template_id"],
        service_id=service.id,
        document_id=uuid.uuid4(),
        type=data["type"],
        name=data["name"],
        mime_type=data["mime_type"],
        file_size=len(data["file_data"]),  # Update to uploaded_file["file_size"] after dd-api updated
        status=FILE_STATUS_PENDING_VIRUS_SCAN,
    )
    dao_create_file(file)

    return jsonify(files_schema.dump(file)), 201


@files_blueprint.route("")
def get_files_by_template_id(template_id):
    files = dao_get_files_by_template_id(template_id)

    if not files:
        return jsonify(result="error", message=f"No files found in database for template: {template_id}")

    data = files_schema.dump(files, many=True)
    return jsonify(data)


@files_blueprint.route("/<uuid:file_id>/status", methods=["GET"])
def get_file_status(template_id, file_id):
    fetched_file = dao_get_file_by_id(file_id)
    file = files_schema.dump(fetched_file)
    return jsonify(file), 200


@files_blueprint.route("/<uuid:file_id>", methods=["DELETE"])
def delete_file(template_id, file_id):
    file = dao_get_file_by_id(file_id)
    dao_delete_file(file)

    current_app.logger.info(f"Deleted file: {file_id} template_id {template_id}")
    return "", 204


# TODO: This will be pulled out into a separate route later for the eventbridge lambda
# to access via a token. Just including here for now.
@files_blueprint.route("/<uuid:file_id>/status", methods=["POST"])
def update_file_status(template_id, file_id):
    data = request.get_json()
    validate(data, post_update_file_status_schema)

    file_obj = dao_get_file_by_id(file_id)
    file_obj.status = data["status"]
    dao_update_file(file_obj)

    current_app.logger.info(f"Updated file status for file: {file_id} template_id: {template_id} to {data["status"]}")
    return jsonify(files_schema.dump(file_obj)), 200
