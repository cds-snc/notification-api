from datetime import datetime

from flask import jsonify

from app import api_user, authenticated_service, redis_store
from app.dao import templates_dao
from app.models import ApiKeyPermission
from app.schema_validation import validate
from app.v2.errors import BadRequestError, ForbiddenError
from app.v2.manage_template import v2_manage_template_blueprint
from app.v2.manage_template.get_template import _serialize_template
from app.v2.template.template_schemas import get_template_by_id_request


@v2_manage_template_blueprint.route("/<template_id>", methods=["DELETE"])
def delete_manage_template(template_id):
    if not api_user.has_permission(ApiKeyPermission.MANAGE_TEMPLATES):
        raise ForbiddenError(message="This API key does not have permission to manage templates.")

    validate({"id": template_id}, get_template_by_id_request)

    template = templates_dao.dao_get_template_by_id_and_service_id(template_id, authenticated_service.id)

    if template.archived:
        raise BadRequestError(message="Template is already archived.")

    template.archived = True
    template.updated_at = datetime.utcnow()
    templates_dao.dao_update_template(template)
    redis_store.delete(f"service-{authenticated_service.id}-templates")

    return jsonify(_serialize_template(template)), 200
