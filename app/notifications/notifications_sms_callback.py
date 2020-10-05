from flask import Blueprint
from flask import jsonify

from app.errors import register_errors
from app.notifications.process_client_response import process_sms_client_response

sms_callback_blueprint = Blueprint("sms_callback", __name__, url_prefix="/notifications/sms")
register_errors(sms_callback_blueprint)


@sms_callback_blueprint.route('/sns', methods=['POST'])
def process_sns_response():
    # setting provider_reference = 'send-sms-code' mocks a successful response
    success, errors = process_sms_client_response(None, 'send-sms-code', 'sns')
    return jsonify(result='success', message=success), 200


@sms_callback_blueprint.route('/pinpoint', methods=['POST'])
def process_pinpoint_response():
    # setting provider_reference = 'send-sms-code' mocks a successful response
    success, errors = process_sms_client_response(None, 'send-sms-code', 'pinpoint')
    return jsonify(result='success', message=success), 200
