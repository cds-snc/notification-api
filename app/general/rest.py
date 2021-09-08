from flask import Blueprint, jsonify, request

from app.dao.events_dao import dao_create_event
from app.errors import register_errors, InvalidRequest
from app.schemas import event_schema

general_blueprint = Blueprint("general", __name__, url_prefix="/general")
register_errors(general_blueprint)


@general_blueprint.route("/query_uuid", methods=["GET"])
def querry_uuid():
    uuid = request.args.get("uuid")
    if not uuid:
        errors = {"uuid": ["Missing data for required field."]}
        raise InvalidRequest(errors, status_code=400)
    data = query_uuid(uuid)
    return jsonify(data=data), 200


def create_event():
    data = request.get_json()
    event = event_schema.load(data).data
    dao_create_event(event)
    return jsonify(data=event_schema.dump(event).data), 201
