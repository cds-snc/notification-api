from datetime import datetime

from flask import current_app
from itsdangerous import BadSignature

from app import create_uuid, db, signer_bearer_token
from app.dao.dao_utils import transactional, version_class
from app.models import (
    COMPLAINT_CALLBACK_TYPE,
    DELIVERY_STATUS_CALLBACK_TYPE,
    ServiceCallbackApi,
)


@transactional
def resign_service_callbacks(unsafe: bool = False):
    """Resign the _bearer_token column of the service_callbacks table with (potentially) a new key.

    Args:
        unsafe (bool, optional): resign regardless of whether the unsign step fails with a BadSignature.
        Defaults to False.

    Raises:
        e: BadSignature if the unsign step fails and unsafe is False.
    """
    rows = ServiceCallbackApi.query.all()  # noqa
    current_app.logger.info(f"Resigning {len(rows)} service_callbacks")

    for row in rows:
        if row._bearer_token:
            try:
                unsigned_token = getattr(row, "bearer_token")  # unsign the token
            except BadSignature as e:
                if unsafe:
                    unsigned_token = signer_bearer_token.verify_unsafe(row._bearer_token)
                else:
                    current_app.logger.error(f"BadSignature for service_callback {row.id}")
                    raise e
            setattr(row, "bearer_token", unsigned_token)  # resigns the token with (potentially) a new signing secret
    db.session.bulk_save_objects(rows)


@transactional
@version_class(ServiceCallbackApi)
def save_service_callback_api(service_callback_api):
    service_callback_api.id = create_uuid()
    service_callback_api.created_at = datetime.utcnow()
    db.session.add(service_callback_api)


@transactional
@version_class(ServiceCallbackApi)
def reset_service_callback_api(service_callback_api, updated_by_id, url=None, bearer_token=None):
    if url:
        service_callback_api.url = url
    if bearer_token:
        service_callback_api.bearer_token = bearer_token
    service_callback_api.updated_by_id = updated_by_id
    service_callback_api.updated_at = datetime.utcnow()

    db.session.add(service_callback_api)


def get_service_callback_api(service_callback_api_id, service_id):
    return ServiceCallbackApi.query.filter_by(id=service_callback_api_id, service_id=service_id).first()


def get_service_delivery_status_callback_api_for_service(service_id):
    return ServiceCallbackApi.query.filter_by(service_id=service_id, callback_type=DELIVERY_STATUS_CALLBACK_TYPE).first()


def get_service_complaint_callback_api_for_service(service_id):
    return ServiceCallbackApi.query.filter_by(service_id=service_id, callback_type=COMPLAINT_CALLBACK_TYPE).first()


@transactional
def delete_service_callback_api(service_callback_api):
    db.session.delete(service_callback_api)
