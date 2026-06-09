from datetime import datetime

from flask import jsonify

from app import api_user, authenticated_service
from app.dao import templates_dao
from app.errors import InvalidRequest
from app.models import ApiKeyPermission
from app.v2.manage_template import v2_manage_template_blueprint
from app.v2.manage_template.get_template import _serialize_template


@v2_manage_template_blueprint.route("/<template_id>", methods=["DELETE"])
def delete_manage_template(template_id):
    if not api_user.has_permission(ApiKeyPermission.MANAGE_TEMPLATES):
        raise InvalidRequest("This API key does not have permission to manage templates.", status_code=403)

    template = templates_dao.dao_get_template_by_id_and_service_id(template_id, authenticated_service.id)

    if template.archived:
        raise InvalidRequest("Template is already archived.", status_code=400)

    template.archived = True
    template.updated_at = datetime.utcnow()
    templates_dao.dao_update_template(template)

    return jsonify(_serialize_template(template)), 200
