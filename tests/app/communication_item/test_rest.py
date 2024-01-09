""" Test CRUD endpoints for the CommunicationItem model. """

import pytest
from app.models import CommunicationItem
from uuid import UUID, uuid4


#############
# Create
#############


@pytest.mark.parametrize(
    'post_data,expected_status',
    [
        ({}, 400),
        ({'id': 'invalid uuid4'}, 400),
        ({'id': '39247cfc-a52d-4b2b-b9a9-2ef8a20190cb'}, 400),
        ({'name': 'communication item tests'}, 400),
        ({'va_profile_item_id': 1}, 400),
        ({'name': 'communication item tests', 'va_profile_item_id': 1}, 201),
        ({'default_send_indicator': False, 'name': '', 'va_profile_item_id': 1}, 400),
        ({'default_send_indicator': False, 'name': 'communication item tests', 'va_profile_item_id': 1}, 201),
        ({'default_send_indicator': False, 'name': 'communication item tests', 'va_profile_item_id': -5}, 400),
        ({'default_send_indicator': False, 'name': 'communication item tests', 'va_profile_item_id': 0}, 400),
        (
            {
                'default_send_indicator': False,
                'id': '39247cfc-a52d-4b2b-b9a9-2ef8a20190cb',
                'name': 'communication item tests',
                'va_profile_item_id': 1,
            },
            400,
        ),
    ],
)
def test_create_communication_item(notify_db_session, admin_request, post_data, expected_status):
    """
    The post data must contain "name" and "va_profile_item_id".  "default_send_indicatior" is optional.
    The post data must not contain "id".
    """

    response = admin_request.post('communication_item.create_communication_item', post_data, expected_status)

    if expected_status == 201:
        assert isinstance(response, dict), response
        assert response['default_send_indicator'] is post_data.get('default_send_indicator', True)
        assert response['name'] == 'communication item tests'
        assert response['va_profile_item_id'] == 1
        assert isinstance(UUID(response['id']), UUID)
    elif expected_status == 400:
        assert isinstance(response, dict) and 'errors' in response, response
        assert isinstance(response['errors'], list) and len(response['errors']) == 1
        assert isinstance(response['errors'][0], dict)
        assert response['errors'][0]['error'] in ('DataError', 'IntegrityError', 'ValidationError')
        assert 'message' in response['errors'][0]
    else:
        raise RuntimeError('This is a programming error.')


@pytest.mark.parametrize(
    'post_data',
    [
        {'name': 'communication item tests', 'va_profile_item_id': 2},
        {'name': 'different name', 'va_profile_item_id': 1},
    ],
)
def test_create_communication_item_duplicates(notify_db_session, admin_request, post_data):
    """The name and va_profile_item_id must be unique in the table."""

    communication_item = CommunicationItem(id=uuid4(), va_profile_item_id=1, name='communication item tests')
    notify_db_session.session.add(communication_item)
    notify_db_session.session.commit()

    response = admin_request.post('communication_item.create_communication_item', post_data, 400)

    assert isinstance(response, dict) and 'errors' in response, response
    assert isinstance(response['errors'], list) and len(response['errors']) == 1
    assert isinstance(response['errors'][0], dict)
    assert response['errors'][0]['error'] == 'IntegrityError'
    assert 'message' in response['errors'][0]


#############
# Retrieve
#############


def test_get_all_communication_items(notify_db_session, admin_request):
    """
    This test creates a CommunicationItem instance to ensure at least one instance is in the
    database, but it doesn't assume that only one instance exists because fixtures create them.
    """

    communication_item = CommunicationItem(id=uuid4(), va_profile_item_id=5, name='communication item tests')
    notify_db_session.session.add(communication_item)
    notify_db_session.session.commit()

    response = admin_request.get('communication_item.get_all_communication_items', 200)
    assert isinstance(response['data'], list)

    for communication_item in response['data']:
        assert isinstance(communication_item, dict)
        assert isinstance(communication_item['default_send_indicator'], bool)
        assert communication_item['default_send_indicator'], 'Should be True by default.'
        assert isinstance(communication_item['name'], str) and communication_item['name']
        assert isinstance(communication_item['va_profile_item_id'], int)
        assert isinstance(UUID(communication_item['id']), UUID)


def test_get_communication_item(notify_db_session, admin_request):
    communication_item = CommunicationItem(id=uuid4(), va_profile_item_id=1, name='communication item tests')
    notify_db_session.session.add(communication_item)
    notify_db_session.session.commit()

    response = admin_request.get(
        'communication_item.get_communication_item', 200, communication_item_id=communication_item.id
    )

    assert isinstance(response, dict), response
    assert isinstance(response['default_send_indicator'], bool)
    assert response['default_send_indicator'], 'Should be True by default.'
    assert response['name'] == 'communication item tests'
    assert response['va_profile_item_id'] == 1
    assert isinstance(UUID(response['id']), UUID)


@pytest.mark.parametrize('communication_item_id', ["doesn't exist", '39247cfc-a52d-4b2b-b9a9-2ef8a20190cb'])
def test_get_communication_item_not_found(notify_db_session, admin_request, communication_item_id):
    response = admin_request.get(
        'communication_item.get_communication_item', 404, communication_item_id=communication_item_id
    )

    assert isinstance(response, dict), response


#############
# Update
#############


@pytest.mark.parametrize(
    'post_data,expected_status',
    [
        ({}, 400),
        ({'name': 1}, 400),
        ({'name': ''}, 400),
        ({'name': 'communication item tests'}, 200),
        ({'va_profile_item_id': 'not a number'}, 400),
        ({'va_profile_item_id': -5}, 400),
        ({'va_profile_item_id': 0}, 400),
        ({'va_profile_item_id': 1}, 200),
        ({'name': 'different name'}, 200),
        ({'va_profile_item_id': 2}, 200),
        ({'default_send_indicator': False}, 200),
        ({'name': 'different name', 'va_profile_item_id': 2, 'default_send_indicator': False}, 200),
    ],
)
def test_partially_update_communication_item(notify_db_session, admin_request, post_data, expected_status):
    communication_item = CommunicationItem(id=uuid4(), va_profile_item_id=1, name='communication item tests')
    notify_db_session.session.add(communication_item)
    notify_db_session.session.commit()
    assert communication_item.default_send_indicator, 'Should be True by default.'

    response = admin_request.patch(
        'communication_item.partially_update_communication_item',
        post_data,
        expected_status,
        communication_item_id=str(communication_item.id),
    )

    assert isinstance(response, dict), response

    if expected_status == 200:
        if 'name' in post_data:
            assert communication_item.name == post_data['name']
            assert response['name'] == post_data['name']
        if 'va_profile_item_id' in post_data:
            assert communication_item.va_profile_item_id == post_data['va_profile_item_id']
            assert response['va_profile_item_id'] == post_data['va_profile_item_id']
        if 'default_send_indicator' in post_data:
            assert isinstance(communication_item.default_send_indicator, bool)
            assert communication_item.default_send_indicator is post_data['default_send_indicator']
            assert response['default_send_indicator'] is post_data['default_send_indicator']
    elif expected_status == 400:
        assert response['errors'][0]['error'] in ('DataError', 'IntegrityError', 'ValidationError')
        assert 'message' in response['errors'][0]


@pytest.mark.parametrize('communication_item_id', ["doesn't exist", '39247cfc-a52d-4b2b-b9a9-2ef8a20190cb'])
def test_partially_update_communication_item_not_found(notify_db_session, admin_request, communication_item_id):
    admin_request.patch(
        'communication_item.partially_update_communication_item',
        {'va_profile_item_id': 2},
        404,
        communication_item_id=communication_item_id,
    )


#############
# Delete
#############


def test_delete_communication_item(notify_db_session, admin_request):
    communication_item = CommunicationItem(id=uuid4(), va_profile_item_id=5, name='communication item tests')
    communication_item_id = communication_item.id
    notify_db_session.session.add(communication_item)
    notify_db_session.session.commit()

    # Ensure the new CommunicationItem instance is in the database.
    assert CommunicationItem.query.get(communication_item_id) is not None

    admin_request.delete(
        'communication_item.delete_communication_item', 202, communication_item_id=communication_item_id
    )

    # Ensure communication_item1 is not in the database.
    assert CommunicationItem.query.get(communication_item_id) is None


@pytest.mark.parametrize('communication_item_id', ["doesn't exist", '39247cfc-a52d-4b2b-b9a9-2ef8a20190cb'])
def test_delete_communication_item_not_found(notify_db_session, admin_request, communication_item_id):
    response = admin_request.delete(
        'communication_item.delete_communication_item', 404, communication_item_id=communication_item_id
    )

    assert isinstance(response, dict), response
