import uuid

import pytest
from freezegun import freeze_time

from tests.app.db import (
    create_service_inbound_api,
    create_service_callback_api
)

from app.models import ServiceInboundApi, ServiceCallbackApi, DELIVERY_STATUS_CALLBACK_TYPE


def test_create_service_inbound_api(admin_request, sample_service):
    data = {
        "url": "https://some.service/inbound-sms",
        "bearer_token": "some-unique-string",
        "updated_by_id": str(sample_service.users[0].id)
    }
    resp_json = admin_request.post(
        'service_callback.create_service_inbound_api',
        service_id=sample_service.id,
        _data=data,
        _expected_status=201
    )

    resp_json = resp_json["data"]
    assert resp_json["id"]
    assert resp_json["service_id"] == str(sample_service.id)
    assert resp_json["url"] == "https://some.service/inbound-sms"
    assert resp_json["updated_by_id"] == str(sample_service.users[0].id)
    assert resp_json["created_at"]
    assert not resp_json["updated_at"]


def test_set_service_inbound_api_raises_404_when_service_does_not_exist(notify_db, admin_request):
    data = {
        "url": "https://some.service/inbound-sms",
        "bearer_token": "some-unique-string",
        "updated_by_id": str(uuid.uuid4())
    }
    response = admin_request.post(
        'service_callback.create_service_inbound_api',
        service_id=uuid.uuid4(),
        _data=data,
        _expected_status=404
    )
    assert response['message'] == 'No result found'


def test_update_service_inbound_api_updates_url(admin_request, sample_service):
    service_inbound_api = create_service_inbound_api(service=sample_service,
                                                     url="https://original_url.com")

    data = {
        "url": "https://another_url.com",
        "updated_by_id": str(sample_service.users[0].id)
    }

    response = admin_request.post(
        'service_callback.update_service_inbound_api',
        service_id=sample_service.id,
        inbound_api_id=service_inbound_api.id,
        _data=data
    )

    assert response["data"]["url"] == "https://another_url.com"
    assert service_inbound_api.url == "https://another_url.com"


def test_update_service_inbound_api_updates_bearer_token(admin_request, sample_service):
    service_inbound_api = create_service_inbound_api(service=sample_service,  # nosec
                                                     bearer_token="some_super_secret")
    data = {
        "bearer_token": "different_token",
        "updated_by_id": str(sample_service.users[0].id)
    }

    admin_request.post(
        'service_callback.update_service_inbound_api',
        service_id=sample_service.id,
        inbound_api_id=service_inbound_api.id,
        _data=data
    )
    assert service_inbound_api.bearer_token == "different_token"


def test_fetch_service_inbound_api(admin_request, sample_service):
    service_inbound_api = create_service_inbound_api(service=sample_service)

    response = admin_request.get(
        'service_callback.fetch_service_inbound_api',
        service_id=sample_service.id,
        inbound_api_id=service_inbound_api.id,
    )
    assert response["data"] == service_inbound_api.serialize()


def test_delete_service_inbound_api(admin_request, sample_service):
    service_inbound_api = create_service_inbound_api(sample_service)

    response = admin_request.delete(
        'service_callback.remove_service_inbound_api',
        service_id=sample_service.id,
        inbound_api_id=service_inbound_api.id,
    )

    assert response is None
    assert ServiceInboundApi.query.count() == 0


def test_create_service_callback_api(notify_db, admin_request, sample_service):
    data = {
        "url": "https://some.service/delivery-receipt-endpoint",
        "bearer_token": "some-unique-string",
        "notification_statuses": ["failed"],
        "updated_by_id": str(sample_service.users[0].id)
    }

    resp_json = admin_request.post(
        'service_callback.create_service_callback_api',
        service_id=sample_service.id,
        _data=data,
        _expected_status=201
    )

    resp_json = resp_json["data"]
    assert resp_json["id"]
    assert resp_json["service_id"] == str(sample_service.id)
    assert resp_json["url"] == "https://some.service/delivery-receipt-endpoint"
    assert resp_json["updated_by_id"] == str(sample_service.users[0].id)
    assert resp_json["created_at"]
    assert not resp_json["updated_at"]
    assert resp_json.get("bearer_token") is None
    from app.dao.service_callback_api_dao import get_service_callback_api
    created_service_callback_api = get_service_callback_api(resp_json["id"], resp_json["service_id"])
    assert created_service_callback_api.callback_type == DELIVERY_STATUS_CALLBACK_TYPE


def test_create_service_callback_api_raises_400_when_no_status_in_request(admin_request, sample_service):
    data = {
        "url": "https://some.service/delivery-receipt-endpoint",
        "bearer_token": "some-unique-string",
        "updated_by_id": str(sample_service.users[0].id)
    }

    admin_request.post(
        'service_callback.create_service_callback_api',
        service_id=sample_service.id,
        _data=data,
        _expected_status=400
    )


def test_create_service_callback_api_raises_400_when_notification_status_validation_failed(
        admin_request, notify_db_session
):
    non_existent_status = 'nonexistent_failed'
    data = {
        "url": "https://some.service/delivery-receipt-endpoint",
        "bearer_token": "some-unique-string",
        "notification_statuses": [non_existent_status],
        "updated_by_id": str(uuid.uuid4())
    }

    admin_request.post(
        'service_callback.create_service_callback_api',
        service_id=uuid.uuid4(),
        _data=data,
        _expected_status=400
    )


@pytest.mark.parametrize(
    'add_url, url, expected_response',
    [
        (False, None, 'url is a required property'),
        (True, None, 'url is not a valid https url'),
        (True, 'broken.url', 'url is not a valid https url')
    ]
)
def test_create_service_callback_api_raises_400_when_url_validation_failed(
        admin_request, sample_service, add_url, url, expected_response
):
    data = {
        "bearer_token": "some-unique-string",
        "notification_statuses": ["failed"],
        "updated_by_id": str(sample_service.users[0].id)
    }
    if add_url:
        data['url'] = url

    resp_json = admin_request.post(
        'service_callback.create_service_callback_api',
        service_id=sample_service.id,
        _data=data,
        _expected_status=400
    )

    assert resp_json['errors'][0]['error'] == 'ValidationError'
    assert resp_json['errors'][0]['message'] == expected_response


def test_create_service_callback_api_raises_404_when_service_does_not_exist(admin_request, notify_db_session):
    data = {
        "url": "https://some.service/delivery-receipt-endpoint",
        "bearer_token": "some-unique-string",
        "notification_statuses": ["failed"],
        "updated_by_id": str(uuid.uuid4())
    }

    resp_json = admin_request.post(
        'service_callback.create_service_callback_api',
        service_id=uuid.uuid4(),
        _data=data,
        _expected_status=404
    )
    assert resp_json['message'] == 'No result found'


@pytest.mark.parametrize(
    'add_bearer_token, bearer_token, expected_response',
    [
        (False, None, 'bearer_token is a required property'),
        (True, None, 'bearer_token None is not of type string'),
        (True, 'too-short', 'bearer_token too-short is too short')
    ]
)
def test_create_service_callback_api_raises_400_when_bearer_token_validation_failed(
        admin_request, sample_service, add_bearer_token, bearer_token, expected_response
):
    data = {
        "url": "https://some.service/delivery-receipt-endpoint",
        "notification_statuses": ["failed"],
        "updated_by_id": str(sample_service.users[0].id)
    }
    if add_bearer_token:
        data['bearer_token'] = bearer_token

    resp_json = admin_request.post(
        'service_callback.create_service_callback_api',
        service_id=sample_service.id,
        _data=data,
        _expected_status=400
    )

    assert resp_json['errors'][0]['error'] == 'ValidationError'
    assert resp_json['errors'][0]['message'] == expected_response


def test_update_service_callback_api_updates_notification_statuses(admin_request, sample_service):
    service_callback_api = create_service_callback_api(service=sample_service,
                                                       notification_statuses=['cancelled'])

    data = {
        "notification_statuses": ["delivered"],
        "updated_by_id": str(sample_service.users[0].id)
    }

    resp_json = admin_request.post(
        'service_callback.update_service_callback_api',
        service_id=sample_service.id,
        callback_api_id=service_callback_api.id,
        _data=data,
        _expected_status=200
    )
    assert resp_json["data"]["notification_statuses"] == ["delivered"]
    assert resp_json.get("bearer_token") is None


@pytest.mark.parametrize(
    'request_data', [
        {
            "invalid_parameter": ["failed"],
            "updated_by_id": "6ce466d0-fd6a-11e5-82f5-e0accb9d11a6"
        },
        {
        }
    ]
)
def test_update_service_callback_api_raises_400_when_wrong_request(admin_request, sample_service, request_data):
    service_callback_api = create_service_callback_api(service=sample_service,
                                                       notification_statuses=['technical-failure'])

    resp_json = admin_request.post(
        'service_callback.update_service_callback_api',
        service_id=sample_service.id,
        callback_api_id=service_callback_api.id,
        _data=request_data,
        _expected_status=400
    )
    assert len(resp_json['errors']) > 0
    for error in resp_json['errors']:
        assert error['message'] is not None


def test_update_service_callback_api_raises_400_when_invalid_status(admin_request, sample_service):
    service_callback_api = create_service_callback_api(service=sample_service,
                                                       notification_statuses=['technical-failure'])

    data = {
        "notification_statuses": ["nonexistent-status"],
        "updated_by_id": str(sample_service.users[0].id)
    }

    resp_json = admin_request.post(
        'service_callback.update_service_callback_api',
        service_id=sample_service.id,
        callback_api_id=service_callback_api.id,
        _data=data,
        _expected_status=400
    )
    assert resp_json['errors'][0]['error'] == 'ValidationError'
    assert 'notification_statuses nonexistent-status is not one of' in resp_json['errors'][0]['message']


def test_update_service_callback_api_updates_url(admin_request, sample_service):
    service_callback_api = create_service_callback_api(service=sample_service,
                                                       url="https://original.url.com")

    data = {
        "url": "https://another.url.com",
        "updated_by_id": str(sample_service.users[0].id)
    }

    resp_json = admin_request.post(
        'service_callback.update_service_callback_api',
        service_id=sample_service.id,
        callback_api_id=service_callback_api.id,
        _data=data
    )
    assert resp_json["data"]["url"] == "https://another.url.com"
    assert service_callback_api.url == "https://another.url.com"


def test_update_service_callback_api_updates_bearer_token(admin_request, sample_service):
    service_callback_api = create_service_callback_api(service=sample_service,  # nosec
                                                       bearer_token="some_super_secret")
    data = {
        "bearer_token": "different_token",
        "updated_by_id": str(sample_service.users[0].id)
    }

    admin_request.post(
        'service_callback.update_service_callback_api',
        service_id=sample_service.id,
        callback_api_id=service_callback_api.id,
        _data=data
    )

    assert service_callback_api.bearer_token == "different_token"


def test_update_service_callback_api_raises_400_with_only_updated_by_id(admin_request, sample_service):
    service_callback_api = create_service_callback_api(service=sample_service,  # nosec
                                                       bearer_token="some_super_secret")
    data = {
        "updated_by_id": str(sample_service.users[0].id)
    }

    resp_json = admin_request.post(
        'service_callback.update_service_callback_api',
        service_id=sample_service.id,
        callback_api_id=service_callback_api.id,
        _data=data,
        _expected_status=400
    )
    assert resp_json['errors'][0]['error'] == 'ValidationError'
    assert 'is not valid' in resp_json['errors'][0]['message']


def test_update_service_callback_api_modifies_updated_at(admin_request, sample_service):
    with freeze_time("2021-05-13 12:00:00.000000"):
        service_callback_api = create_service_callback_api(service=sample_service,  # nosec
                                                           bearer_token="some_super_secret")
        data = {
            "updated_by_id": str(sample_service.users[0].id),
            "url": "https://some.service"
        }

        response_json = admin_request.post(
            'service_callback.update_service_callback_api',
            service_id=sample_service.id,
            callback_api_id=service_callback_api.id,
            _data=data
        )

    assert response_json['data']['updated_at'] == "2021-05-13T12:00:00+00:00"


def test_fetch_service_callback_api(admin_request, sample_service):
    service_callback_api = create_service_callback_api(service=sample_service)

    response = admin_request.get(
        'service_callback.fetch_service_callback_api',
        service_id=sample_service.id,
        callback_api_id=service_callback_api.id,
    )

    assert response["data"] == {
        'created_at': str(service_callback_api.created_at),
        'id': str(service_callback_api.id),
        'notification_statuses': service_callback_api.notification_statuses,
        'service_id': str(service_callback_api.service_id),
        'updated_at': service_callback_api.updated_at,
        'updated_by_id': str(service_callback_api.updated_by_id),
        'url': service_callback_api.url
    }
    assert response["data"].get('bearer_token') is None


def test_delete_service_callback_api(admin_request, sample_service):
    service_callback_api = create_service_callback_api(sample_service)

    response = admin_request.delete(
        'service_callback.remove_service_callback_api',
        service_id=sample_service.id,
        callback_api_id=service_callback_api.id,
    )

    assert response is None
    assert ServiceCallbackApi.query.count() == 0
