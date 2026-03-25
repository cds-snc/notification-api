from flask import Blueprint, current_app, jsonify
from itsdangerous import BadData
from notifications_utils.url_safe_token import check_token

from app import redis_store
from app.dao.notification_history_dao import get_notification_history_by_id
from app.dao.notifications_dao import get_notification_by_id
from app.dao.unsubscribe_request_dao import (
    create_unsubscribe_request_dao,
    get_unbatched_unsubscribe_requests_dao,
    get_unsubscribe_request_by_notification_id_dao,
    get_unsubscribe_request_report_by_id_dao,
    get_unsubscribe_request_reports_dao,
)
from app.errors import InvalidRequest, register_errors
from app.models import UnsubscribeRequestReport
from app.notifications.callbacks import _check_and_queue_unsubscribe_callback_task

one_click_unsubscribe_blueprint = Blueprint("one_click_unsubscribe", __name__)
register_errors(one_click_unsubscribe_blueprint)


@one_click_unsubscribe_blueprint.route("/unsubscribe/<uuid:notification_id>/<string:token>", methods=["POST"])
def one_click_unsubscribe(notification_id, token):
    max_age_seconds = 60 * 60 * 24 * 365  # 1 year

    try:
        # GC Notify uses only SECRET_KEY (no DANGEROUS_SALT)
        email_address = check_token(token, current_app.config["SECRET_KEY"], max_age_seconds)
    except BadData as e:
        errors = {"unsubscribe request": "This is not a valid unsubscribe link."}
        raise InvalidRequest(errors, status_code=404) from e

    # Idempotency: return success if a non-processed request already exists for this notification
    if is_duplicate_unsubscribe_request(notification_id):
        return jsonify(result="success", message="Unsubscribe successful"), 200

    if notification := get_notification_by_id(notification_id):
        unsubscribe_data = get_unsubscribe_request_data(notification, email_address)
    elif notification := get_notification_history_by_id(notification_id):
        unsubscribe_data = get_unsubscribe_request_data(notification, email_address)
    else:
        errors = {"unsubscribe request": "This unsubscribe link is invalid or expired."}
        raise InvalidRequest(errors, status_code=404)

    create_unsubscribe_request_dao(unsubscribe_data)

    redis_store.delete(f"service-{unsubscribe_data['service_id']}-unsubscribe-request-statistics")
    redis_store.delete(f"service-{unsubscribe_data['service_id']}-unsubscribe-request-reports-summary")

    # Fire webhook callback if the service has registered one
    _check_and_queue_unsubscribe_callback_task(unsubscribe_data)

    current_app.logger.info(
        "Received unsubscribe request for notification %s",
        notification_id,
        extra={"notification_id": str(notification_id)},
    )

    return jsonify(result="success", message="Unsubscribe successful"), 200


def get_unsubscribe_request_data(notification, email_address):
    return {
        "notification_id": notification.id,
        "template_id": notification.template_id,
        "template_version": notification.template_version,
        "service_id": notification.service_id,
        "email_address": email_address,
    }


def create_unsubscribe_request_reports_summary(service_id):
    unsubscribe_request_reports = [report.serialize() for report in get_unsubscribe_request_reports_dao(service_id)]
    if unbatched_unsubscribe_requests := get_unbatched_unsubscribe_requests_dao(service_id):
        return [
            UnsubscribeRequestReport.serialize_unbatched_requests(unbatched_unsubscribe_requests)
        ] + unsubscribe_request_reports
    return unsubscribe_request_reports


def is_duplicate_unsubscribe_request(notification_id):
    """
    A duplicate is an unsubscribe_request with the same notification_id of a previously received
    unsubscribe request that has NOT yet been processed by the service that initiated the notification.
    """
    unsubscribe_request = get_unsubscribe_request_by_notification_id_dao(notification_id)
    if not unsubscribe_request:
        return False
    report_id = unsubscribe_request.unsubscribe_request_report_id
    if report_id and get_unsubscribe_request_report_by_id_dao(report_id).processed_by_service_at:
        return False
    return True
