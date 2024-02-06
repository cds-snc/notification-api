import uuid
from app.models import ServiceSmsSender, Service
from datetime import datetime
from flask import current_app
from sqlalchemy.orm.exc import NoResultFound


def test_add_service_sms_sender_calls_dao_method(admin_request, mocker):
    service_id = uuid.uuid4()
    added_service_sms_sender = ServiceSmsSender(created_at=datetime.utcnow())

    dao_add_sms_sender_for_service = mocker.patch(
        'app.service.sms_sender_rest.dao_add_sms_sender_for_service', return_value=added_service_sms_sender
    )

    mocker.patch('app.service.sms_sender_rest.dao_fetch_service_by_id', return_value=Service())

    response_json = admin_request.post(
        'service_sms_sender.add_service_sms_sender',
        service_id=service_id,
        _data={
            'sms_sender': 'second',
            'is_default': False,
        },
        _expected_status=201,
    )

    dao_add_sms_sender_for_service.assert_called_with(service_id=service_id, sms_sender='second', is_default=False)
    assert response_json == added_service_sms_sender.serialize()


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


def test_update_service_sms_sender(
    admin_request,
    sample_service,
    sample_sms_sender_v2,
):
    service = sample_service()
    sender_specifics = {'data': 'This is something specific.'}

    service_sms_sender = sample_sms_sender_v2(
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


def test_update_service_sms_sender_does_not_allow_sender_update_for_inbound_number(
    admin_request,
    sample_inbound_number,
    sample_service,
    sample_sms_sender_v2,
):
    service = sample_service()
    inbound_number = sample_inbound_number('12345', service_id=service.id)
    service_sms_sender = sample_sms_sender_v2(
        service_id=service.id, sms_sender='1235', is_default=False, inbound_number_id=inbound_number.id
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


def test_delete_service_sms_sender_can_archive_sms_sender(
    admin_request,
    sample_service,
    sample_sms_sender_v2,
):
    service = sample_service()
    service_sms_sender = sample_sms_sender_v2(service_id=service.id, sms_sender='5678', is_default=False)

    assert not service_sms_sender.archived, 'This should be False by default.'

    admin_request.post(
        'service_sms_sender.delete_service_sms_sender',
        service_id=service.id,
        sms_sender_id=service_sms_sender.id,
    )

    assert service_sms_sender.archived


def test_delete_service_sms_sender_returns_400_if_archiving_inbound_number(
    admin_request,
    sample_service_with_inbound_number,
):
    service = sample_service_with_inbound_number(inbound_number='7654321')
    inbound_number = service.service_sms_senders[0]

    response = admin_request.post(
        'service_sms_sender.delete_service_sms_sender',
        service_id=service.id,
        sms_sender_id=service.service_sms_senders[0].id,
        _expected_status=400,
    )

    assert response == {'message': 'You cannot delete an inbound number.', 'result': 'error'}
    assert not inbound_number.archived


def test_get_service_sms_sender_by_id(
    admin_request,
    sample_service,
    sample_sms_sender_v2,
):
    service_sms_sender = sample_sms_sender_v2(service_id=sample_service().id, sms_sender='1235', is_default=False)

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
    sample_sms_sender_v2,
):
    sender_specifics = {'data': 'This is something specific.'}

    service_sms_sender = sample_sms_sender_v2(
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
