from flask import jsonify, request
from sqlalchemy.orm.exc import NoResultFound

from app import api_user, authenticated_service
from app.dao.template_folder_dao import (
    dao_get_template_folder_by_id_and_service_id,
    dao_update_template_folder,
)
from app.models import ApiKeyPermission
from app.schema_validation import validate
from app.v2.errors import BadRequestError, ForbiddenError
from app.v2.manage_template_folder import v2_manage_template_folder_blueprint
from app.v2.manage_template_folder.folder_schemas import (
    get_template_folder_by_id_request,
    patch_manage_template_folder_request,
)
from app.v2.manage_template_folder.get_folder import _serialize_folder


@v2_manage_template_folder_blueprint.route("/<template_folder_id>", methods=["PATCH"])
def patch_manage_template_folder(template_folder_id):
    if not api_user.has_permission(ApiKeyPermission.MANAGE_TEMPLATES):
        raise ForbiddenError(message="This API key does not have permission to manage templates.")

    validate({"id": template_folder_id}, get_template_folder_by_id_request)

    data = validate(request.get_json() or {}, patch_manage_template_folder_request)

    folder = dao_get_template_folder_by_id_and_service_id(template_folder_id, authenticated_service.id)

    if "name" in data:
        folder.name = data["name"].strip()

    if "parent_folder_id" in data:
        folder.parent = _validated_parent_folder(folder, data["parent_folder_id"])

    dao_update_template_folder(folder)

    return jsonify(_serialize_folder(folder)), 200


def _validated_parent_folder(folder, parent_folder_id):
    if parent_folder_id is None:
        return None

    if str(parent_folder_id) == str(folder.id):
        raise BadRequestError(message="You cannot move a folder to itself")

    try:
        target_folder = dao_get_template_folder_by_id_and_service_id(parent_folder_id, authenticated_service.id)
    except NoResultFound:
        raise BadRequestError(message="parent_folder_id not found")

    if folder.is_parent_of(target_folder):
        raise BadRequestError(message="You cannot move a folder to one of its subfolders")

    return target_folder
