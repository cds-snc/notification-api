from flask import jsonify

from app import DATETIME_FORMAT, api_user, authenticated_service
from app.dao import templates_dao
from app.errors import InvalidRequest
from app.models import ApiKeyPermission
from app.v3.template import v3_template_blueprint


@v3_template_blueprint.route("/<template_id>", methods=["GET"])
def get_template_by_id(template_id):
    if not api_user.has_permission(ApiKeyPermission.MANAGE_TEMPLATES):
        raise InvalidRequest("This API key does not have permission to manage templates.", status_code=403)

    template = templates_dao.dao_get_template_by_id_and_service_id(template_id, authenticated_service.id)

    return jsonify(_serialize_template(template)), 200


def _serialize_template(template) -> dict:
    folder_id = str(template.folder.id) if template.folder else None

    return {
        "id": str(template.id),
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
        "folder_id": folder_id,
        "archived": template.archived,
    }
