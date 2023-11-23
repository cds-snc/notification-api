from datetime import datetime

import werkzeug
from flask import Blueprint, current_app, jsonify, request

from app import DATETIME_FORMAT
from app.dao.api_key_dao import (
    expire_api_key,
    get_api_key_by_secret,
    update_compromised_api_key_info,
)
from app.dao.fact_notification_status_dao import (
    get_api_key_ranked_by_notifications_created,
    get_last_send_for_api_key,
    get_total_notifications_sent_for_api_key,
)
from app.dao.services_dao import dao_fetch_service_by_id
from app.errors import InvalidRequest, register_errors
from app.service.sender import send_notification_to_service_users

api_key_blueprint = Blueprint("api_key", __name__)
register_errors(api_key_blueprint)

sre_tools_blueprint = Blueprint("sre_tools", __name__)
register_errors(sre_tools_blueprint)


@api_key_blueprint.route("/<uuid:api_key_id>/summary-statistics", methods=["GET"])
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
        "last_send": last_send,
    }
    data["total_sends"] = data["email_sends"] + data["sms_sends"]
    return jsonify(data=data)


@api_key_blueprint.route("/ranked-by-notifications-created/<n_days_back>", methods=["GET"])
def get_api_keys_ranked(n_days_back):
    try:
        n_days_back = int(n_days_back)
    except ValueError:
        return jsonify(data=[])
    # the notifications table doesn't hold data older than 7 days
    if n_days_back > 7 or n_days_back < 1:
        return jsonify(data=[])

    _data = get_api_key_ranked_by_notifications_created(n_days_back)
    data = []
    for x in _data:
        data.append(
            {
                "api_key_name": x[0],
                "api_key_type": x[1],
                "service_name": x[2],
                "api_key_id": x[3],
                "service_id": x[4],
                "last_notification_created": x[5].strftime(DATETIME_FORMAT),
                "email_notifications": int(x[6]),
                "sms_notifications": int(x[7]),
                "total_notifications": int(x[8]),
            }
        )
    return jsonify(data=data)


def send_api_key_revocation_email(service_id, api_key_name, api_key_information):
    service = dao_fetch_service_by_id(service_id)
    send_notification_to_service_users(
        service_id=service_id,
        template_id=current_app.config["APIKEY_REVOKE_TEMPLATE_ID"],
        personalisation={
            "service_name": service.name,
            "public_location": api_key_information["url"],
            "key_name": api_key_name,
        },
        include_user_fields=["name"],
    )


@sre_tools_blueprint.route("/api-key-revoke", methods=["POST"])
def revoke_api_keys():
    """
    This method accepts a single api key and revokes it. The data is of the form:
    {
        "token": "gcntfy-key-name-uuid-uuid",
        "type": "mycompany_api_token",
        "url": "https://github.com/octocat/Hello-World/blob/12345600b9cbe38a219f39a9941c9319b600c002/foo/bar.txt",
        "source": "content",
    }

    The function does 4 things:
    1. Finds the api key by API key itself
    2. Revokes the API key
    3. Saves the source and url into the compromised_key_info field
    4. TODO: Sends the service owners of the api key an email notification indicating that the key has been revoked
    """
    try:
        api_key_data = request.get_json()
        # check for correct payload
        if (
            isinstance(api_key_data, list)
            or api_key_data.get("token") is None
            or api_key_data.get("type") is None
            or api_key_data.get("url") is None
            or api_key_data.get("source") is None
        ):
            raise InvalidRequest("Invalid payload", status_code=400)
    except werkzeug.exceptions.BadRequest as errors:
        raise InvalidRequest(errors, status_code=400)

    # Step 1
    try:
        # take last 36 chars of string so that it works even if the full key is provided.
        api_key_token = api_key_data["token"][-36:]
        api_key = get_api_key_by_secret(api_key_token)
    except Exception:
        current_app.logger.error(
            "Revoke api key: API key not found for token {}".format(api_key_data["token"])
            if api_key_data.get("token")
            else "Revoke api key: no token provided"
        )
        raise InvalidRequest("Invalid request", status_code=400)

    # Step 2
    expire_api_key(api_key.service_id, api_key.id)

    current_app.logger.info("Expired api key {} for service {}".format(api_key.id, api_key.service_id))

    # Step 3
    update_compromised_api_key_info(
        api_key.service_id,
        api_key.id,
        {
            "time_of_revocation": str(datetime.utcnow()),
            "type": api_key_data["type"],
            "url": api_key_data["url"],
            "source": api_key_data["source"],
        },
    )

    # Step 4
    send_api_key_revocation_email(api_key.service_id, api_key.name, api_key_data)

    return jsonify(result="ok"), 201
