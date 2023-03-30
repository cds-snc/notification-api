from app.dao.service_callback_api_dao import (save_service_callback_api)
from app.dao.service_callback_dao import (dao_get_callback_include_payload_status)
from app.models import ServiceCallback, WEBHOOK_CHANNEL_TYPE, \
    NOTIFICATION_SENT, DELIVERY_STATUS_CALLBACK_TYPE


def test_dao_service_callback(sample_service):
    service_callback_api = ServiceCallback(
        service_id=sample_service.id,
        url="https://some_service/callback_endpoint",
        bearer_token="some_unique_string",
        updated_by_id=sample_service.users[0].id,
        callback_type=DELIVERY_STATUS_CALLBACK_TYPE,
        notification_statuses=NOTIFICATION_SENT,
        callback_channel=WEBHOOK_CHANNEL_TYPE,
        include_provider_payload=True
    )

    save_service_callback_api(service_callback_api)
    include_payload_status = dao_get_callback_include_payload_status(
        service_id=service_callback_api.service_id,
        service_callback_type=DELIVERY_STATUS_CALLBACK_TYPE)
    assert isinstance(include_payload_status, bool)
