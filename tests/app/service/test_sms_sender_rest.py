from datetime import datetime
from unittest.mock import ANY
import uuid

from flask import current_app
import pytest
from sqlalchemy import select
from sqlalchemy.orm.exc import NoResultFound

from app.models import ServiceSmsSender, Service


def test_add_service_sms_sender_calls_dao_method(admin_request, mocker):
    service_id = uuid.uuid4()
    provider_id = str(uuid.uuid4())
    added_service_sms_sender = ServiceSmsSender(created_at=datetime.utcnow())

    dao_add_sms_sender_for_service = mocker.patch(
        'app.service.sms_sender_rest.dao_add_sms_sender_for_service', return_value=added_service_sms_sender
    )

    mocker.patch('app.service.sms_sender_rest.dao_fetch_service_by_id', return_value=Service())

    response_json = admin_request.post(
        'service_sms_sender.add_service_sms_sender',
        service_id=service_id,
        _data={
            'description': 'test description',
            'is_default': False,
            'provider_id': provider_id,
            'sms_sender': 'second',
        },
        _expected_status=201,
    )

    dao_add_sms_sender_for_service.assert_called_with(
        service_id=service_id,
        description='test description',
        is_default=False,
        provider_id=provider_id,
        sms_sender='second',
    )
    assert response_json == added_service_sms_sender.serialize()


def test_add_service_sms_sender_returns_201_with_proper_data(admin_request, sample_provider, sample_service) -> None:
    service = sample_service()
    provider = sample_provider(display_name='test_provider_name')

    test_sms_sender = '+1234567890'

    expected_data = {
        'archived': False,
        'created_at': ANY,
        'description': 'test description',
        'id': ANY,
        'inbound_number_id': None,
        'is_default': True,
        'provider_id': str(provider.id),
        'provider_name': 'test_provider_name',
        'rate_limit': None,
        'rate_limit_interval': None,
        'service_id': str(service.id),
        'sms_sender': test_sms_sender,
        'sms_sender_specifics': {},
        'updated_at': ANY,
    }

    response_json = admin_request.post(
        'service_sms_sender.add_service_sms_sender',
        service_id=service.id,
        _data={
            'description': 'test description',
            'is_default': True,
            'provider_id': str(provider.id),
            'sms_sender': test_sms_sender,
        },
        _expected_status=201,
    )

    assert response_json == expected_data


@pytest.mark.parametrize(
    'include_provider, include_description, valid_sms_sender',
    [(True, False, True), (False, True, True), (False, False, True), (True, True, False)],
    ids=['no_provider', 'no_description', 'no_provider_nor_description', 'sms_sender_too_long'],
)
def test_add_service_sms_sender_returns_400_error_with_invalid_request_data(
    admin_request,
    sample_provider,
    sample_service,
    include_provider,
    include_description,
    valid_sms_sender,
) -> None:
    service = sample_service()
    provider = sample_provider(display_name='test_provider_name')

    resp_json = admin_request.post(
        'service_sms_sender.add_service_sms_sender',
        service_id=service.id,
        _data={
            'description': 'test description' if include_description else None,
            'is_default': True,
            'provider_id': str(provider.id) if include_provider else None,
            'sms_sender': '+1234567890' if valid_sms_sender else '1' * 257,
        },
        _expected_status=400,
    )

    assert 'ValidationError' in resp_json['errors'][0]['error']


def test_add_service_sms_sender_returns_400_error_when_provider_does_not_exist(admin_request, sample_service) -> None:
    service = sample_service()
    missing_provider_id = str(uuid.uuid4())

    resp_json = admin_request.post(
        'service_sms_sender.add_service_sms_sender',
        service_id=service.id,
        _data={
            'description': 'test description',
            'is_default': True,
            'provider_id': missing_provider_id,
            'sms_sender': '+1234567890',
        },
        _expected_status=400,
    )

    assert 'No provider details found' in resp_json['message']


def test_add_service_sms_sender_return_404_when_service_does_not_exist(admin_request, mocker):
    mocker.patch('app.service.sms_sender_rest.dao_fetch_service_by_id', side_effect=NoResultFound())

    response_json = admin_request.post(
        'service_sms_sender.add_service_sms_sender', service_id=uuid.uuid4(), _expected_status=404
    )

    assert response_json['result'] == 'error'
    assert response_json['message'] == 'No result found'


def test_add_service_sms_sender_return_404_when_rate_limit_too_small(admin_request, mocker):
    added_service_sms_sender = ServiceSmsSender(created_at=datetime.utcnow(), rate_limit=1)
    mocker.patch('app.service.sms_sender_rest.dao_add_sms_sender_for_service', return_value=added_service_sms_sender)
    mocker.patch('app.service.sms_sender_rest.dao_fetch_service_by_id', return_value=Service())

    response_json = admin_request.post(
        'service_sms_sender.add_service_sms_sender',
        service_id=uuid.uuid4(),
        _data={
            'sms_sender': 'second',
            'is_default': False,
            'rate_limit': 0,
        },
        _expected_status=400,
    )

    assert response_json['errors'][0]['error'] == 'ValidationError'
    assert response_json['errors'][0]['message'] == 'rate_limit 0 is less than the minimum of 1'


def test_add_service_sms_sender_new_sender_to_default(
    notify_db_session,
    admin_request,
    sample_provider,
    sample_service,
):
    """
    Create a service with 1 associated ServiceSmsSender instance, which is default, and then create a
    new ServiceSmsSender as default.  The initial ServiceSmsSender instance should no longer be default.
    """

    # This fixture also should create a default ServiceSmsSender instance.
    service = sample_service()

    provider = sample_provider()

    stmt = select(ServiceSmsSender.id).where(
        ServiceSmsSender.service_id == service.id, ServiceSmsSender.is_default.is_(True)
    )
    initial_sms_sender_id = notify_db_session.session.execute(stmt).scalar_one()

    # Attempt to create a new default sms_sender.  The request should return the new default ServiceSmsSender instance.
    response_json = admin_request.post(
        'service_sms_sender.add_service_sms_sender',
        service_id=service.id,
        _data={
            'description': 'test description',
            'provider_id': str(provider.id),
            'sms_sender': '54321',
            'is_default': True,
        },
        _expected_status=201,
    )

    assert response_json['is_default']
    assert notify_db_session.session.get(ServiceSmsSender, response_json['id']).is_default
    assert not notify_db_session.session.get(ServiceSmsSender, initial_sms_sender_id).is_default


def test_update_service_sms_sender_sender_specifics(
    admin_request,
    sample_service,
    sample_sms_sender,
):
    """
    Test updating the sender_specifics field of a given service_sms_sender row.  This test does
    not attempt to affect the default sender.
    """

    service = sample_service()
    sender_specifics = {'data': 'This is something specific.'}

    service_sms_sender = sample_sms_sender(
        service_id=service.id, sms_sender='1235', is_default=False, sms_sender_specifics=sender_specifics
    )

    assert service_sms_sender.sms_sender_specifics == sender_specifics
    sender_specifics = {'new_data': 'This is something else.', 'some_int': 42}

    response_json = admin_request.post(
        'service_sms_sender.update_service_sms_sender',
        service_id=service.id,
        sms_sender_id=service_sms_sender.id,
        _data={
            'sms_sender': 'second',
            'is_default': False,
            'sms_sender_specifics': sender_specifics,
        },
        _expected_status=200,
    )

    assert response_json['sms_sender'] == 'second'
    assert not response_json['inbound_number_id']
    assert not response_json['is_default']
    assert response_json['sms_sender_specifics'] == sender_specifics


def test_update_service_sms_sender_provider(
    admin_request,
    sample_provider,
    sample_service,
    sample_sms_sender,
) -> None:
    """
    Test updating the provider_id field of a given service_sms_sender row. This test does
    not attempt to affect the default sender.
    """

    service = sample_service()
    provider = sample_provider()

    service_sms_sender = sample_sms_sender(
        service_id=service.id,
        sms_sender='1235',
        is_default=False,
    )

    assert service_sms_sender.provider_id is None

    response_json = admin_request.post(
        'service_sms_sender.update_service_sms_sender',
        service_id=service.id,
        sms_sender_id=service_sms_sender.id,
        _data={
            'sms_sender': 'second',
            'is_default': False,
            'provider_id': str(provider.id),
        },
        _expected_status=200,
    )

    assert response_json['sms_sender'] == 'second'
    assert not response_json['inbound_number_id']
    assert not response_json['is_default']
    assert response_json['provider_id'] == str(provider.id)


def test_update_service_sms_sender_checks_for_invalid_provider(
    admin_request,
    sample_provider,
    sample_service,
    sample_sms_sender,
) -> None:
    """
    Test updating the provider_id field of a given service_sms_sender row. This test does
    not attempt to affect the default sender.
    """

    service = sample_service()
    provider = sample_provider()

    service_sms_sender = sample_sms_sender(
        service_id=service.id,
        sms_sender='1235',
        is_default=False,
        provider_id=provider.id,
    )

    assert service_sms_sender.provider_id == provider.id

    response_json = admin_request.post(
        'service_sms_sender.update_service_sms_sender',
        service_id=service.id,
        sms_sender_id=service_sms_sender.id,
        _data={
            'sms_sender': '54321',
            'is_default': False,
            'provider_id': str(uuid.uuid4()),
        },
        _expected_status=400,
    )

    assert response_json['result'] == 'error'
    assert 'No provider details found' in response_json['message']


def test_update_service_sms_sender_does_not_allow_sender_update_for_inbound_number(
    admin_request,
    sample_inbound_number,
    sample_service,
    sample_sms_sender,
):
    service = sample_service()
    inbound_number = sample_inbound_number(service_id=service.id)
    service_sms_sender = sample_sms_sender(
        service_id=service.id, sms_sender=inbound_number.number, is_default=False, inbound_number_id=inbound_number.id
    )
    payload = {'sms_sender': 'second', 'is_default': True, 'inbound_number_id': str(inbound_number.id)}
    admin_request.post(
        'service_sms_sender.update_service_sms_sender',
        service_id=service.id,
        sms_sender_id=service_sms_sender.id,
        _data=payload,
        _expected_status=400,
    )


def test_update_service_sms_sender_return_404_when_service_does_not_exist(admin_request, mocker):
    mocker.patch('app.service.sms_sender_rest.dao_fetch_service_by_id', side_effect=NoResultFound())

    response = admin_request.post(
        'service_sms_sender.update_service_sms_sender',
        service_id=uuid.uuid4(),
        sms_sender_id=uuid.uuid4(),
        _expected_status=404,
    )

    assert response['result'] == 'error'
    assert response['message'] == 'No result found'


def test_update_service_sms_sender_existing_sender_to_default(
    notify_db_session,
    admin_request,
    sample_service,
    sample_sms_sender,
):
    """
    Create a service with 2 associated ServiceSmsSender instances, one of which is default, and then Swap which
    sender is the default.  The initial ServiceSmsSender instance should no longer be default.
    """

    # This fixture also should create a default ServiceSmsSender instance.
    service = sample_service()

    stmt = select(ServiceSmsSender).where(
        ServiceSmsSender.service_id == service.id, ServiceSmsSender.is_default.is_(True)
    )
    service_sms_sender1 = notify_db_session.session.execute(stmt).scalar_one()
    service_sms_sender2 = sample_sms_sender(service_id=service.id, is_default=False)

    assert service_sms_sender1.is_default
    assert not service_sms_sender2.is_default

    # Attempt to make service_sms_sender2 the default.
    response_json = admin_request.post(
        'service_sms_sender.update_service_sms_sender',
        service_id=service.id,
        sms_sender_id=service_sms_sender2.id,
        _data={
            'is_default': True,
        },
        _expected_status=200,
    )

    assert response_json['is_default']
    assert not service_sms_sender1.is_default
    assert service_sms_sender2.is_default


def test_get_service_sms_sender_by_id(
    admin_request,
    sample_service,
    sample_sms_sender,
):
    service_sms_sender = sample_sms_sender(service_id=sample_service().id, sms_sender='1235', is_default=False)

    response_json = admin_request.get(
        'service_sms_sender.get_service_sms_sender_by_id',
        service_id=service_sms_sender.service_id,
        sms_sender_id=service_sms_sender.id,
        _expected_status=200,
    )

    assert response_json == service_sms_sender.serialize()


def test_get_service_sms_sender_by_id_returns_404_when_service_sms_sender_does_not_exist(admin_request, mocker):
    mocker.patch('app.service.sms_sender_rest.dao_get_service_sms_sender_by_id', side_effect=NoResultFound())

    admin_request.get(
        'service_sms_sender.get_service_sms_sender_by_id',
        service_id=uuid.uuid4(),
        sms_sender_id=uuid.uuid4(),
        _expected_status=404,
    )


def test_get_service_sms_senders_for_service(
    admin_request,
    sample_service,
    sample_sms_sender,
):
    sender_specifics = {'data': 'This is something specific.'}

    service_sms_sender = sample_sms_sender(
        service_id=sample_service().id, sms_sender='second', is_default=False, sms_sender_specifics=sender_specifics
    )

    response_json = admin_request.get(
        'service_sms_sender.get_service_sms_senders_for_service',
        service_id=service_sms_sender.service_id,
        _expected_status=200,
    )

    assert len(response_json) == 2
    assert response_json[0]['is_default']
    assert response_json[0]['sms_sender'] == current_app.config['FROM_NUMBER']
    assert not response_json[1]['is_default']
    assert response_json[1]['sms_sender'] == 'second'
    assert response_json[1]['sms_sender_specifics'] == sender_specifics


def test_get_service_sms_senders_for_service_returns_404_when_service_does_not_exist(admin_request, mocker):
    # mocker.patch('app.service.sms_sender_rest.dao_fetch_service_by_id', side_effect=NoResultFound())

    admin_request.get(
        'service_sms_sender.get_service_sms_senders_for_service', service_id=uuid.uuid4(), _expected_status=404
    )
