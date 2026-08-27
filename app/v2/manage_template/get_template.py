from flask import jsonify

from app import DATETIME_FORMAT, api_user, authenticated_service
from app.dao import templates_dao
from app.models import ApiKeyPermission
from app.schema_validation import validate
from app.v2.errors import ForbiddenError
from app.v2.manage_template import v2_manage_template_blueprint
from app.v2.template.template_schemas import get_template_by_id_request


@v2_manage_template_blueprint.route("/<template_id>", methods=["GET"])
def get_template_by_id_enhanced(template_id):
    if not api_user.has_permission(ApiKeyPermission.MANAGE_TEMPLATES):
        raise ForbiddenError(message="This API key does not have permission to manage templates.")

    validate({"id": template_id}, get_template_by_id_request)

    template = templates_dao.dao_get_template_by_id_and_service_id(template_id, authenticated_service.id)
    return jsonify(_serialize_template(template)), 200


def _serialize_template(template) -> dict:
    folder_id = str(template.folder.id) if template.folder else None

    return {
        "id": str(template.id),
        "service_id": str(template.service_id),
        "service_name": template.service.name,
        "name": template.name,
        "type": template.template_type,
        "created_at": template.created_at.strftime(DATETIME_FORMAT),
        "updated_at": template.updated_at.strftime(DATETIME_FORMAT) if template.updated_at else None,
        "created_by": template.created_by.email_address,
        "version": template.version,
        "body": template.content,
        "subject": template.subject if template.template_type != "sms" else None,
        "postage": template.postage,
        "template_category_id": str(template.template_category_id) if template.template_category_id else None,
        "template_category_name": str(template.template_category.name_en) if template.template_category else None,
        "folder_id": folder_id,
        "archived": template.archived,
    }
