from flask import Blueprint, jsonify
from app import DATETIME_FORMAT
from app.dao.fact_notification_status_dao import (
    get_total_notifications_sent_for_api_key,
    get_last_send_for_api_key,
    get_api_key_ranked_by_notifications_created
)
from app.errors import register_errors

api_key_blueprint = Blueprint('api_key', __name__)
register_errors(api_key_blueprint)


@api_key_blueprint.route('/<uuid:api_key_id>/summary-statistics', methods=['GET'])
def get_api_key_stats(api_key_id):
    result_array_totals = get_total_notifications_sent_for_api_key(api_key_id)
    result_array_last_send = get_last_send_for_api_key(api_key_id)
    try:
        last_send = result_array_last_send[0][0].strftime(DATETIME_FORMAT)
    except IndexError:
        last_send = None

    result_dict_totals = dict(result_array_totals)
    data = {
        "api_key_id": api_key_id,
        "email_sends": 0 if "email" not in result_dict_totals else result_dict_totals["email"],
        "sms_sends": 0 if "sms" not in result_dict_totals else result_dict_totals["sms"],
        "last_send": last_send
    }
    data["total_sends"] = data["email_sends"] + data["sms_sends"]
    return jsonify(data=data)


@api_key_blueprint.route('/ranked-by-notifications-created/<n_days_back>', methods=['GET'])
def get_api_keys_ranked(n_days_back):
    try:
        n_days_back = int(n_days_back)
    except ValueError:
        return jsonify(data=[])
    # the notifications table doesn't hold data older than 7 days
    if (n_days_back > 7 or n_days_back < 1):
        return jsonify(data=[])

    _data = get_api_key_ranked_by_notifications_created(n_days_back)
    data = []
    for x in _data:
        data.append({
            "api_key_name": x[0],
            "api_key_type": x[1],
            "service_name": x[2],
            "api_key_id": x[3],
            "service_id": x[4],
            "last_notification_created": x[5].strftime(DATETIME_FORMAT),
            "email_notifications": int(x[6]),
            "sms_notifications": int(x[7]),
            "total_notifications": int(x[8])
        })
    return jsonify(data=data)
