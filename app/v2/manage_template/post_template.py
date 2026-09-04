from flask import jsonify, request
from jsonschema import ValidationError
from notifications_utils import EMAIL_CHAR_COUNT_LIMIT, SMS_CHAR_COUNT_LIMIT, TEMPLATE_NAME_CHAR_COUNT_LIMIT
from notifications_utils.template import HTMLEmailTemplate, SMSMessageTemplate
from sqlalchemy.orm.exc import NoResultFound

from app import api_user, authenticated_service, redis_store
from app.dao import templates_dao
from app.dao.template_categories_dao import dao_get_all_template_categories, dao_get_template_category_by_id
from app.dao.template_folder_dao import dao_get_template_folder_by_id_and_service_id
from app.models import EMAIL_TYPE, SMS_TYPE, ApiKeyPermission, Template
from app.notifications.validators import service_has_permission
from app.schema_validation import validate
from app.utils import get_public_notify_type_text
from app.v2.errors import (
    BadRequestError,
    ForbiddenError,
    TemplateCategoryNotFoundError,
    TemplateCategoryValidationError,
)
from app.v2.manage_template import v2_manage_template_blueprint
from app.v2.manage_template.get_template import _serialize_template
from app.v2.manage_template.template_schemas import post_manage_template_request


@v2_manage_template_blueprint.route("", methods=["POST"])
def post_manage_template():
    if not api_user.has_permission(ApiKeyPermission.MANAGE_TEMPLATES):
        raise ForbiddenError(message="This API key does not have permission to manage templates.")

    try:
        data = validate(request.get_json() or {}, post_manage_template_request)
    except ValidationError as e:
        if "template_category_id" in str(e):
            return _template_category_error_response(
                TemplateCategoryValidationError.__name__,
                _template_category_validation_message(e),
            )
        raise

    try:
        _validate_template_category_id(data["template_category_id"])
    except TemplateCategoryNotFoundError as e:
        if e.message == TemplateCategoryNotFoundError.message:
            return _template_category_error_response(TemplateCategoryNotFoundError.__name__, e.message)
        raise

    folder = _validate_parent_folder(data)
    template = Template.from_json(
        {
            **data,
            "service": authenticated_service.id,
            "created_by": api_user.created_by_id,
        },
    )

    if not service_has_permission(template.template_type, authenticated_service.permissions):
        message = "Creating {} templates is not allowed".format(get_public_notify_type_text(template.template_type))
        raise ForbiddenError(message=message)

    _raise_if_content_or_name_over_limit(template)

    templates_dao.dao_create_template(template, folder=folder)

    redis_store.delete(f"service-{authenticated_service.id}-templates")

    return jsonify(_serialize_template(template)), 201


def _validate_template_category_id(template_category_id):
    try:
        dao_get_template_category_by_id(template_category_id)
    except NoResultFound:
        raise TemplateCategoryNotFoundError()


def _validate_parent_folder(data):
    parent_folder_id = data.pop("parent_folder_id", None)
    if parent_folder_id:
        try:
            return dao_get_template_folder_by_id_and_service_id(parent_folder_id, authenticated_service.id)
        except NoResultFound:
            raise BadRequestError(message="parent_folder_id not found")
    return None


def _raise_if_content_or_name_over_limit(template):
    if _content_count_greater_than_limit(template.content, template.template_type):
        char_limit = SMS_CHAR_COUNT_LIMIT if template.template_type == SMS_TYPE else EMAIL_CHAR_COUNT_LIMIT
        message = "Content has a character count greater than the limit of {}".format(char_limit)
        raise BadRequestError(message=message)

    if _template_name_over_char_limit(template.name, template.content, template.template_type):
        message = "Template name must be less than {} characters".format(TEMPLATE_NAME_CHAR_COUNT_LIMIT)
        raise BadRequestError(message=message)


def _content_count_greater_than_limit(content, template_type):
    if template_type == EMAIL_TYPE:
        template = HTMLEmailTemplate({"content": content, "subject": "placeholder", "template_type": template_type})
        return template.is_message_too_long()
    if template_type == SMS_TYPE:
        template = SMSMessageTemplate({"content": content, "template_type": template_type})
        return template.is_message_too_long()
    return False


def _template_name_over_char_limit(name, content, template_type):
    return HTMLEmailTemplate(
        {"name": name, "content": content, "subject": "placeholder", "template_type": template_type}
    ).is_name_too_long()


def _template_category_error_response(error_type, message):
    template_categories = dao_get_all_template_categories(hidden=False)

    errors = [{"error": error_type, "message": message}]
    if not template_categories:
        errors.append(
            {
                "error": "TemplateCategoryUnavailable",
                "message": "Template categories are unavailable. Please contact support; the template categories endpoint may be down.",
            }
        )

    return (
        jsonify(
            status_code=400,
            errors=errors,
            template_categories=[
                {"template_category_id": str(template_category.id), "name": template_category.name_en}
                for template_category in template_categories
            ],
        ),
        400,
    )


def _template_category_validation_message(error):
    if "required property" in str(error):
        return "template_category_id is a required property"
    return TemplateCategoryValidationError.message
