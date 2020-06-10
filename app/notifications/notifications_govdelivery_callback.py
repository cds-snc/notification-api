from datetime import datetime

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound

from app import statsd_client
from app.clients.email.govdelivery_client import map_govdelivery_status_to_notify_status
from app.dao import notifications_dao
from app.errors import register_errors

govdelivery_callback_blueprint = Blueprint("govdelivery_callback", __name__, url_prefix="/notifications/govdelivery")
register_errors(govdelivery_callback_blueprint)


@govdelivery_callback_blueprint.route('', methods=['POST'])
def process_govdelivery_response():
    data = request.form
    reference = data['message_url'].split("/")[-1]

    try:
        notification = notifications_dao.dao_get_notification_by_reference(reference)

        govdelivery_status = data['status']
        notify_status = map_govdelivery_status_to_notify_status(govdelivery_status)

        current_app.logger.info(
            'Govdelivery callback for notification {} has status "{}", which maps to notification-api status "{}"'
            .format(notification.id, govdelivery_status, notify_status)
        )

        notifications_dao._update_notification_status(notification, notify_status)

        statsd_client.incr('callback.govdelivery.{}'.format(notify_status))

        if notification.sent_at:
            statsd_client.timing_with_dates(
                'callback.govdelivery.elapsed-time', datetime.utcnow(), notification.sent_at)

    except MultipleResultsFound:
        current_app.logger.warning(
            'Govdelivery callback for reference {} found multiple notifications'.format(reference)
        )
        pass

    except NoResultFound:
        current_app.logger.warning(
            'Govdelivery callback for reference {} did not find any notifications'.format(reference)
        )
        pass

    return jsonify(result='success'), 200
