from flask import Blueprint, jsonify
from flask import json
from flask import request

from app.clients.email.govdelivery_client import map_govdelivery_status_to_notify_status
from app.dao import notifications_dao
from app.errors import register_errors

govdelivery_callback_blueprint = Blueprint("govdelivery_callback", __name__, url_prefix="/notifications/govdelivery")
register_errors(govdelivery_callback_blueprint)


@govdelivery_callback_blueprint.route('', methods=['POST'])
def process_govdelivery_response():
    data = json.loads(request.data)

    reference = data['message_url'].split("/")[-1]

    notifications_dao.dao_get_notification_by_reference(reference)

    map_govdelivery_status_to_notify_status(data['status'])

    return jsonify(result='success'), 200
