from flask import jsonify, request

from app import authenticated_service
from app.dao import templates_dao
from app.schema_validation import validate
from app.v2.templates import v2_templates_blueprint
from app.v2.templates.templates_schemas import get_all_template_request


@v2_templates_blueprint.route("", methods=["GET"])
def get_templates():
    data = validate(request.args.to_dict(), get_all_template_request)

    templates = templates_dao.dao_get_all_templates_for_service(authenticated_service.id, data.get("type"))

    return jsonify(templates=[template.serialize() for template in templates]), 200
