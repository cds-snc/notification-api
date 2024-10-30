import pytest

from app.constants import DELIVERY_STATUS_CALLBACK_TYPE, NOTIFICATION_SENT, WEBHOOK_CHANNEL_TYPE
from app.dao.service_callback_api_dao import save_service_callback_api
from app.dao.service_callback_dao import dao_get_callback_include_payload_status
from app.models import ServiceCallback


@pytest.mark.parametrize('include_provider_payload', [True, False])
def test_dao_get_callback_include_payload_status(
    sample_service,
    include_provider_payload,
):
    """Test that we can correctly determine if payload should be included"""
    service = sample_service()

    # build a service callback
    service_callback_api = ServiceCallback(
        service_id=service.id,
        url='https://some_service/callback_endpoint',
        bearer_token='some_unique_string',
        updated_by_id=service.users[0].id,
        callback_type=DELIVERY_STATUS_CALLBACK_TYPE,
        notification_statuses=NOTIFICATION_SENT,
        callback_channel=WEBHOOK_CHANNEL_TYPE,
        include_provider_payload=include_provider_payload,
    )

    # create a service callback
    save_service_callback_api(service_callback_api)

    # retrieve the payload status
    include_payload_status = dao_get_callback_include_payload_status(
        service_id=service_callback_api.service_id, service_callback_type=DELIVERY_STATUS_CALLBACK_TYPE
    )

    # confirm payload is boolean and that it matches what was built in the service callback
    assert isinstance(include_payload_status, bool)
    assert include_payload_status is include_provider_payload
