from flask import Blueprint, jsonify, request

from app.dao.inbound_numbers_dao import (
    dao_create_inbound_number,
    dao_get_inbound_numbers,
    dao_get_inbound_number_for_service,
    dao_get_available_inbound_numbers,
    dao_set_inbound_number_active_flag,
    dao_update_inbound_number
)
from app.errors import register_errors
from app.inbound_number.inbound_number_schema import post_create_inbound_number_schema, \
    post_update_inbound_number_schema
from app.models import InboundNumber
from app.schema_validation import validate

inbound_number_blueprint = Blueprint('inbound_number', __name__, url_prefix='/inbound-number')
register_errors(inbound_number_blueprint)


@inbound_number_blueprint.route('', methods=['GET'])
def get_inbound_numbers():
    inbound_numbers = [i.serialize() for i in dao_get_inbound_numbers()]

    return jsonify(data=inbound_numbers if inbound_numbers else [])


@inbound_number_blueprint.route('', methods=['POST'])
def create_inbound_number():
    data = request.get_json()

    validate(data, post_create_inbound_number_schema)

    inbound_number = InboundNumber(**data)
    dao_create_inbound_number(inbound_number)
    return jsonify(data=inbound_number.serialize()), 201


@inbound_number_blueprint.route('/<uuid:inbound_number_id>', methods=['POST'])
def update_inbound_number(inbound_number_id):
    data = request.get_json()

    validate(data, post_update_inbound_number_schema)

    inbound_number = dao_update_inbound_number(inbound_number_id, data)
    return jsonify(data=inbound_number.serialize()), 201


@inbound_number_blueprint.route('/service/<uuid:service_id>', methods=['GET'])
def get_inbound_number_for_service(service_id):
    inbound_number = dao_get_inbound_number_for_service(service_id)

    return jsonify(data=inbound_number.serialize() if inbound_number else {})


@inbound_number_blueprint.route('/service/<uuid:service_id>/off', methods=['POST'])
def post_set_inbound_number_off(service_id):
    dao_set_inbound_number_active_flag(service_id, active=False)
    return jsonify(), 204


@inbound_number_blueprint.route('/available', methods=['GET'])
def get_available_inbound_numbers():
    inbound_numbers = [i.serialize() for i in dao_get_available_inbound_numbers()]

    return jsonify(data=inbound_numbers if inbound_numbers else [])
