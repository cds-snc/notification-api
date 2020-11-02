from flask import Blueprint
from flask import jsonify

from app.errors import register_errors

sms_callback_blueprint = Blueprint("sms_callback", __name__, url_prefix="/notifications/sms")
register_errors(sms_callback_blueprint)


@sms_callback_blueprint.route('/sns', methods=['POST'])
def process_sns_response():
    # We don't valid callbacks for this provider yet, mock a reponse
    # This would be required to record if a text is delivered or
    # for billing purposes
    # Look at process_client_response._process_for_status later
    success = "sns callback succeeded: send-sms-code"
    return jsonify(result='success', message=success), 200


@sms_callback_blueprint.route('/pinpoint', methods=['POST'])
def process_pinpoint_response():
    # We don't valid callbacks for this provider yet, mock a reponse
    # This would be required to record if a text is delivered or
    # for billing purposes
    # Look at process_client_response._process_for_status later
    success = "pinpoint callback succeeded: send-sms-code"
    return jsonify(result='success', message=success), 200
