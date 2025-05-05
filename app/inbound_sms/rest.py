from flask import Blueprint, jsonify, request

from notifications_utils.recipients import try_validate_and_format_phone_number

from app.dao.inbound_sms_dao import (
    dao_get_inbound_sms_for_service,
    dao_get_inbound_sms_by_id,
)
from app.dao.service_data_retention_dao import fetch_service_data_retention_by_notification_type
from app.errors import register_errors
from app.schema_validation import validate

from app.inbound_sms.inbound_sms_schemas import get_inbound_sms_for_service_schema

inbound_sms = Blueprint('inbound_sms', __name__, url_prefix='/service/<uuid:service_id>/inbound-sms')

register_errors(inbound_sms)


@inbound_sms.route('', methods=['POST'])
def post_inbound_sms_for_service(service_id):
    form = validate(request.get_json(), get_inbound_sms_for_service_schema)
    user_number = form.get('phone_number')

    if user_number:
        # we use this to normalise to an international phone number - but this may fail if it's an alphanumeric
        user_number = try_validate_and_format_phone_number(user_number)

    inbound_data_retention = fetch_service_data_retention_by_notification_type(service_id, 'sms')
    limit_days = inbound_data_retention.days_of_retention if inbound_data_retention else 7

    results = dao_get_inbound_sms_for_service(service_id, user_number=user_number, limit_days=limit_days)
    return jsonify(data=[row.serialize() for row in results])


@inbound_sms.route('/<uuid:inbound_sms_id>', methods=['GET'])
def get_inbound_by_id(
    service_id,
    inbound_sms_id,
):
    message = dao_get_inbound_sms_by_id(service_id, inbound_sms_id)

    return jsonify(message.serialize()), 200
