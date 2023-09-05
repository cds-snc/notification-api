import werkzeug
from flask import Blueprint, current_app, jsonify, request

from app import DATETIME_FORMAT
from app.config import QueueNames
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
from app.dao.services_dao import dao_fetch_active_users_for_service
from app.dao.templates_dao import dao_get_template_by_id
from app.errors import InvalidRequest, register_errors
from app.models import KEY_TYPE_NORMAL, Service
from app.notifications.process_notifications import (
    persist_notification,
    send_notification_to_queue,
)
from app.schemas import email_data_request_schema

api_key_blueprint = Blueprint("api_key", __name__)
register_errors(api_key_blueprint)


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


def send_api_key_revokation_email(service_id, api_key_name, api_key_information):
    """
    TODO: this function if not ready yet. It needs a template to be created.
    """
    pass
    email = email_data_request_schema.load(request.get_json())

    users_to_send_to = dao_fetch_active_users_for_service(service_id)

    template = dao_get_template_by_id(current_app.config["API_KEY_REVOKED_TEMPLATE_ID"])  # this template currently doesn't exist
    service = Service.query.get(current_app.config["NOTIFY_SERVICE_ID"])
    users_service = Service.query.get(service_id)
    for user_to_send_to in users_to_send_to:
        saved_notification = persist_notification(
            template_id=template.id,
            template_version=template.version,
            recipient=email["email"],
            service=service,
            personalisation={
                "user_name": user_to_send_to.name,
                "api_key_name": api_key_name,
                "service_name": users_service.name,
                "api_key_information": api_key_information,
            },
            notification_type=template.template_type,
            api_key_id=None,
            key_type=KEY_TYPE_NORMAL,
            reply_to_text=service.get_default_reply_to_email_address(),
        )

        send_notification_to_queue(saved_notification, False, queue=QueueNames.NOTIFY)


@api_key_blueprint.route("/revoke-api-keys", methods=["POST"])
def revoke_api_keys():
    """
    We take a list of api keys and revoke them. The data is of the form:
    [
        {
            "token": "NMIfyYncKcRALEXAMPLE",
            "type": "mycompany_api_token",
            "url": "https://github.com/octocat/Hello-World/blob/12345600b9cbe38a219f39a9941c9319b600c002/foo/bar.txt",
            "source": "content",
        }
    ]

    The function does 3 things:
    1. Finds the api key by the token
    2. Revokes the api key
    3. Saves the source and url into the compromised_key_info field
    4. Sends the service owners of the api key an email notification indicating that the key has been revoked
    """
    try:
        data = request.get_json()
    except werkzeug.exceptions.BadRequest as errors:
        raise InvalidRequest(errors, status_code=400)

    # Step 1
    for api_key_data in data:
        try:
            # take last 36 chars of string so that it works even if the full key is provided.
            api_key_token = api_key_data["token"][-36:]
            api_key = get_api_key_by_secret(api_key_token)
        except Exception:
            current_app.logger.error(f"API key not found for token {api_key_data['type']}")
            continue  # skip to next api key

        # Step 2
        expire_api_key(api_key.service_id, api_key.id)

        # Step 3
        update_compromised_api_key_info(
            api_key.service_id,
            api_key.id,
            {
                "url": api_key_data["url"],
                "source": api_key_data["source"],
            },
        )

        # Step 4
        send_api_key_revokation_email(api_key.service_id, api_key.name, api_key_data)
