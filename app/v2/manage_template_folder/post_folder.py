from flask import jsonify, request
from sqlalchemy.orm.exc import NoResultFound

from app import api_user, authenticated_service
from app.dao.service_user_dao import dao_get_active_service_users
from app.dao.template_folder_dao import (
    dao_create_template_folder,
    dao_get_template_folder_by_id_and_service_id,
)
from app.models import ApiKeyPermission, TemplateFolder
from app.schema_validation import validate
from app.v2.errors import BadRequestError, ForbiddenError
from app.v2.manage_template_folder import v2_manage_template_folder_blueprint
from app.v2.manage_template_folder.folder_schemas import post_manage_template_folder_request
from app.v2.manage_template_folder.get_folder import _serialize_folder


@v2_manage_template_folder_blueprint.route("", methods=["POST"])
def post_manage_template_folder():
    if not api_user.has_permission(ApiKeyPermission.MANAGE_TEMPLATES):
        raise ForbiddenError(message="This API key does not have permission to manage templates.")

    data = validate(request.get_json() or {}, post_manage_template_folder_request)

    parent_folder_id = data.get("parent_folder_id")
    if parent_folder_id:
        try:
            parent_folder = dao_get_template_folder_by_id_and_service_id(parent_folder_id, authenticated_service.id)
        except NoResultFound:
            raise BadRequestError(message="parent_folder_id not found")
        # New subfolders inherit access from their parent to stay visible in the admin UI.
        users_with_permission = parent_folder.users
    else:
        # Root folders are shared with everyone on the service, matching the admin UI behaviour.
        users_with_permission = dao_get_active_service_users(authenticated_service.id)

    folder = TemplateFolder(
        service_id=authenticated_service.id,
        name=data["name"].strip(),
        parent_id=parent_folder_id,
        users=users_with_permission,
    )

    dao_create_template_folder(folder)

    return jsonify(_serialize_folder(folder)), 201
