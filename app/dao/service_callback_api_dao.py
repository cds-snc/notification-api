from datetime import datetime

from app import db, create_uuid
from app.dao.dao_utils import transactional, version_class
from app.models import ServiceCallback

from app.models import DELIVERY_STATUS_CALLBACK_TYPE, COMPLAINT_CALLBACK_TYPE, NOTIFICATION_STATUS_TYPES_COMPLETED


@transactional
@version_class(ServiceCallback)
def save_service_callback_api(service_callback_api):
    service_callback_api.id = create_uuid()
    service_callback_api.created_at = datetime.utcnow()
    if service_callback_api.callback_type == DELIVERY_STATUS_CALLBACK_TYPE and \
            not service_callback_api.notification_statuses:
        service_callback_api.notification_statuses = NOTIFICATION_STATUS_TYPES_COMPLETED
    db.session.add(service_callback_api)


@transactional
@version_class(ServiceCallback)
def reset_service_callback_api(service_callback_api, updated_by_id, url=None, bearer_token=None):
    if url:
        service_callback_api.url = url
    if bearer_token:
        service_callback_api.bearer_token = bearer_token
    service_callback_api.updated_by_id = updated_by_id
    service_callback_api.updated_at = datetime.utcnow()

    db.session.add(service_callback_api)


@transactional
@version_class(ServiceCallback)
def store_service_callback_api(service_callback_api):
    service_callback_api.updated_at = datetime.utcnow()
    db.session.add(service_callback_api)


def get_service_callbacks(service_id):
    return ServiceCallback.query.filter_by(service_id=service_id).all()


def get_service_callback_api(service_callback_api_id, service_id):
    return ServiceCallback.query.filter_by(id=service_callback_api_id, service_id=service_id).first()


def get_service_callback_api_for_service(service_id):
    return ServiceCallback.query.filter_by(service_id=service_id).first()


def get_service_delivery_status_callback_api_for_service(service_id, notification_status):
    return db.session.query(ServiceCallback).filter(
        ServiceCallback.notification_statuses.contains([notification_status]),
        ServiceCallback.service_id == service_id,
        ServiceCallback.callback_type == DELIVERY_STATUS_CALLBACK_TYPE
    ).first()


def get_service_complaint_callback_api_for_service(service_id):
    return ServiceCallback.query.filter_by(
        service_id=service_id,
        callback_type=COMPLAINT_CALLBACK_TYPE
    ).first()


@transactional
def delete_service_callback_api(service_callback_api):
    db.session.delete(service_callback_api)
