from flask import Blueprint, jsonify
from app.dao.fact_notification_status_dao import get_total_notifications_sent_for_api_key

from app.errors import register_errors

api_key_blueprint = Blueprint('api_key', __name__)
register_errors(api_key_blueprint)


@api_key_blueprint.route('/<uuid:api_key_id>/total-sends', methods=['GET'])
def get_api_key_stats_3(api_key_id):
    total_sends = get_total_notifications_sent_for_api_key(api_key_id)[0]
    return jsonify(data={"total_sends": total_sends, "api_key_id": api_key_id})
