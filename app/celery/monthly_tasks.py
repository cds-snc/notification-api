from datetime import datetime

from flask import current_app
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.exc import SQLAlchemyError

from app import notify_celery
from app.dao.api_key_dao import resign_api_keys
from app.dao.service_callback_api_dao import resign_service_callbacks
from app.dao.inbound_sms_dao import resign_inbound_sms


@notify_celery.task(name="resign-service-callbacks")
@statsd(namespace="tasks")
def resign_service_callbacks_task():
    try:
        start = datetime.utcnow()
        resign_service_callbacks()
        current_app.logger.info(f"resign-service-callbacks job started {start} finished {datetime.utcnow()}")
    except SQLAlchemyError:
        current_app.logger.exception("Failed to resign callbacks")
        raise


@notify_celery.task(name="resign-api-keys")
@statsd(namespace="tasks")
def resign_api_keys_task():
    try:
        start = datetime.utcnow()
        resign_api_keys()
        current_app.logger.info(f"resign-api-keys job started {start} finished {datetime.utcnow()}")
    except SQLAlchemyError:
        current_app.logger.exception("Failed to resign api keys")
        raise



@notify_celery.task(name="resign-inbound-sms")
@statsd(namespace="tasks")
def resign_inbound_sms_task():
    try:
        start = datetime.utcnow()
        resign_inbound_sms()
        current_app.logger.info(f"resign-inbound-sms job started {start} finished {datetime.utcnow()}")
    except SQLAlchemyError:
        current_app.logger.exception("Failed to resign inbound_sms")
        raise
