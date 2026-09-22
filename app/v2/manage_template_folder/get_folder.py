from flask import jsonify

from app import api_user, authenticated_service
from app.dao.template_folder_dao import dao_get_template_folder_by_id_and_service_id
from app.models import ApiKeyPermission
from app.schema_validation import validate
from app.v2.errors import ForbiddenError
from app.v2.manage_template_folder import v2_manage_template_folder_blueprint
from app.v2.manage_template_folder.folder_schemas import get_template_folder_by_id_request


@v2_manage_template_folder_blueprint.route("", methods=["GET"])
def get_manage_template_folders():
    if not api_user.has_permission(ApiKeyPermission.MANAGE_TEMPLATES):
        raise ForbiddenError(message="This API key does not have permission to manage templates.")

    folders = [_serialize_folder(folder) for folder in authenticated_service.all_template_folders]
    return jsonify(template_folders=folders), 200


@v2_manage_template_folder_blueprint.route("/<template_folder_id>", methods=["GET"])
def get_manage_template_folder_by_id(template_folder_id):
    if not api_user.has_permission(ApiKeyPermission.MANAGE_TEMPLATES):
        raise ForbiddenError(message="This API key does not have permission to manage templates.")

    validate({"id": template_folder_id}, get_template_folder_by_id_request)

    folder = dao_get_template_folder_by_id_and_service_id(template_folder_id, authenticated_service.id)
    return jsonify(_serialize_folder(folder)), 200


def _serialize_folder(folder) -> dict:
    return {
        "id": str(folder.id),
        "service_id": str(folder.service_id),
        "name": folder.name,
        "parent_folder_id": str(folder.parent_id) if folder.parent_id else None,
        "users_with_permission": folder.get_users_with_permission(),
    }
