from flask import jsonify, request
from jsonschema import ValidationError
from sqlalchemy.orm.exc import NoResultFound

from app import api_user, authenticated_service
from app.dao import templates_dao
from app.dao.template_categories_dao import dao_get_template_category_by_id
from app.dao.template_folder_dao import dao_get_template_folder_by_id_and_service_id
from app.errors import InvalidRequest
from app.models import ApiKeyPermission
from app.schema_validation import validate
from app.v2.manage_template import v2_manage_template_blueprint
from app.v2.manage_template.get_template import _serialize_template
from app.v2.manage_template.post_template import (
    _get_validation_message,
    _raise_if_content_or_name_over_limit,
    _template_category_error_response,
)
from app.v2.manage_template.template_schemas import patch_manage_template_request


@v2_manage_template_blueprint.route("/<template_id>", methods=["PATCH"])
def patch_manage_template(template_id):
    if not api_user.has_permission(ApiKeyPermission.MANAGE_TEMPLATES):
        raise InvalidRequest("This API key does not have permission to manage templates.", status_code=403)

    try:
        data = validate(request.get_json() or {}, patch_manage_template_request)
    except ValidationError as e:
        if "template_category_id" in str(e):
            return _template_category_error_response("ValidationError", _get_validation_message(e))
        raise

    template = templates_dao.dao_get_template_by_id_and_service_id(template_id, authenticated_service.id)

    if "template_category_id" in data:
        try:
            dao_get_template_category_by_id(data["template_category_id"])
        except NoResultFound:
            return _template_category_error_response("InvalidRequest", "template_category_id not found")

    if "parent_folder_id" in data:
        parent_folder_id = data.pop("parent_folder_id")
        if parent_folder_id:
            try:
                template.folder = dao_get_template_folder_by_id_and_service_id(parent_folder_id, authenticated_service.id)
            except NoResultFound:
                raise InvalidRequest("parent_folder_id not found", status_code=400)
        else:
            template.folder = None

    for field in ("name", "content", "subject", "template_category_id"):
        if field in data:
            setattr(template, field, data[field])

    _raise_if_content_or_name_over_limit(template)

    templates_dao.dao_update_template(template)

    return jsonify(_serialize_template(template)), 200
