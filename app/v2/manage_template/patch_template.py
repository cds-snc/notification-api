from flask import jsonify, request
from jsonschema import ValidationError
from notifications_utils.clients.redis import template_version_cache_key
from sqlalchemy.orm.exc import NoResultFound

from app import api_user, authenticated_service, redis_store
from app.dao import templates_dao
from app.dao.template_categories_dao import dao_get_template_category_by_id
from app.dao.template_folder_dao import dao_get_template_folder_by_id_and_service_id
from app.models import ApiKeyPermission
from app.schema_validation import validate
from app.v2.errors import (
    BadRequestError,
    ForbiddenError,
    TemplateCategoryNotFoundError,
    TemplateCategoryValidationError,
)
from app.v2.manage_template import v2_manage_template_blueprint
from app.v2.manage_template.get_template import _serialize_template
from app.v2.manage_template.post_template import (
    _raise_if_content_or_name_over_limit,
    _template_category_error_response,
)
from app.v2.manage_template.template_schemas import patch_manage_template_request
from app.v2.template.template_schemas import get_template_by_id_request


@v2_manage_template_blueprint.route("/<template_id>", methods=["PATCH"])
def patch_manage_template(template_id):
    if not api_user.has_permission(ApiKeyPermission.MANAGE_TEMPLATES):
        raise ForbiddenError(message="This API key does not have permission to manage templates.")

    validate({"id": template_id}, get_template_by_id_request)

    try:
        data = validate(request.get_json() or {}, patch_manage_template_request)
    except ValidationError as e:
        if "template_category_id" in str(e):
            return _template_category_error_response(
                TemplateCategoryValidationError.__name__,
                TemplateCategoryValidationError.message,
            )
        raise
    template = templates_dao.dao_get_template_by_id_and_service_id(template_id, authenticated_service.id)

    if "template_category_id" in data:
        try:
            dao_get_template_category_by_id(data["template_category_id"])
        except NoResultFound:
            return _template_category_error_response(
                TemplateCategoryNotFoundError.__name__,
                TemplateCategoryNotFoundError.message,
            )

    old_category_id = str(template.template_category_id) if template.template_category_id else None

    if "parent_folder_id" in data:
        parent_folder_id = data.pop("parent_folder_id")
        if parent_folder_id:
            try:
                template.folder = dao_get_template_folder_by_id_and_service_id(parent_folder_id, authenticated_service.id)
            except NoResultFound:
                raise BadRequestError(message="parent_folder_id not found")
        else:
            template.folder = None

    for field in ("name", "content", "subject", "template_category_id"):
        if field in data:
            setattr(template, field, data[field])

    _raise_if_content_or_name_over_limit(template)

    templates_dao.dao_update_template(template)
    redis_store.delete(f"service-{str(template.service_id)}-templates")
    redis_store.delete(template_version_cache_key(template_id))
    redis_store.delete(f"template-{str(template_id)}-versions")

    if "template_category_id" in data:
        new_category_id = data["template_category_id"]
        if old_category_id:
            redis_store.delete(f"template_category-{old_category_id}")
        redis_store.delete(f"template_category-{new_category_id}")
        redis_store.delete("template_categories")

    return jsonify(_serialize_template(template)), 200
