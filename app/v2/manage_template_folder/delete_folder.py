from flask import jsonify

from app import api_user, authenticated_service
from app.dao.template_folder_dao import (
    dao_delete_template_folder,
    dao_get_template_folder_by_id_and_service_id,
)
from app.models import ApiKeyPermission
from app.schema_validation import validate
from app.v2.errors import BadRequestError, ForbiddenError
from app.v2.manage_template_folder import v2_manage_template_folder_blueprint
from app.v2.manage_template_folder.folder_schemas import get_template_folder_by_id_request
from app.v2.manage_template_folder.get_folder import _serialize_folder


@v2_manage_template_folder_blueprint.route("/<template_folder_id>", methods=["DELETE"])
def delete_manage_template_folder(template_folder_id):
    if not api_user.has_permission(ApiKeyPermission.MANAGE_TEMPLATES):
        raise ForbiddenError(message="This API key does not have permission to manage templates.")

    validate({"id": template_folder_id}, get_template_folder_by_id_request)

    folder = dao_get_template_folder_by_id_and_service_id(template_folder_id, authenticated_service.id)

    if folder.subfolders or folder.templates:
        raise BadRequestError(message="Folder is not empty")

    serialized = _serialize_folder(folder)
    dao_delete_template_folder(folder)

    return jsonify(serialized), 200
