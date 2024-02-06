"""
Test CRUD endpoints for the CommunicationItem model.

Tests running locally in Docker expect the table communication_items to contain 4 rows preseeded
via Mountebank.  These rows have va_profile_item_id values 1-4.
"""

from sqlalchemy import delete
from uuid import UUID, uuid4

import pytest

from app.models import CommunicationItem


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
        ({'va_profile_item_id': 5}, 400),
        ({'name': 'communication item tests', 'va_profile_item_id': 6}, 201),
        ({'default_send_indicator': False, 'name': '', 'va_profile_item_id': 7}, 400),
        ({'default_send_indicator': False, 'name': 'communication item tests', 'va_profile_item_id': 8}, 201),
        ({'default_send_indicator': False, 'name': 'communication item tests', 'va_profile_item_id': -5}, 400),
        ({'default_send_indicator': False, 'name': 'communication item tests', 'va_profile_item_id': 0}, 400),
        (
            {
                'default_send_indicator': False,
                'id': '39247cfc-a52d-4b2b-b9a9-2ef8a20190cb',
                'name': 'communication item tests',
                'va_profile_item_id': 5,
            },
            400,
        ),
    ],
)
def test_create_communication_item(
    notify_db_session,
    admin_request,
    post_data,
    expected_status,
):
    """
    The post data must contain "name" and "va_profile_item_id".  "default_send_indicatior" is optional.
    The post data must not contain "id".
    """

    if 'name' in post_data and post_data['name']:
        # Avoid duplicate names when running with multiple threads.
        post_data['name'] += str(uuid4())

    response = admin_request.post('communication_item.create_communication_item', post_data, expected_status)

    if expected_status == 201:
        assert isinstance(response, dict), response
        assert response['default_send_indicator'] is post_data.get('default_send_indicator', True)
        assert response['name'] == post_data['name']
        assert response['va_profile_item_id'] == post_data['va_profile_item_id']
        assert isinstance(UUID(response['id']), UUID)

        # Test clean-up
        communication_item = notify_db_session.session.get(CommunicationItem, response['id'])
        assert communication_item is not None
        notify_db_session.session.delete(communication_item)
        notify_db_session.session.commit()
    elif expected_status == 400:
        assert isinstance(response, dict) and 'errors' in response, response
        assert isinstance(response['errors'], list) and len(response['errors']) == 1
        assert isinstance(response['errors'][0], dict)
        assert response['errors'][0]['error'] in ('DataError', 'IntegrityError', 'ValidationError')
        assert 'message' in response['errors'][0]
    else:
        raise RuntimeError('This is a programming error.')

    # Teardown
    if expected_status == 201:
        stmt = delete(CommunicationItem).where(CommunicationItem.id == response['id'])
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


def test_create_communication_item_duplicate_name(admin_request, sample_communication_item):
    """The name must be unique in the table."""

    communication_item = sample_communication_item()
    post_data = {
        'name': communication_item.name,
        'va_profile_item_id': communication_item.va_profile_item_id + 1,
    }

    response = admin_request.post('communication_item.create_communication_item', post_data, 400)

    assert isinstance(response, dict) and 'errors' in response, response
    assert isinstance(response['errors'], list) and len(response['errors']) == 1
    assert isinstance(response['errors'][0], dict)
    assert 'error' in response['errors'][0]
    assert 'message' in response['errors'][0]


def test_create_communication_item_duplicate_va_profile_item_id(admin_request, sample_communication_item):
    """The va_profile_item_id must be unique in the table."""

    communication_item = sample_communication_item()
    post_data = {
        'name': communication_item.name + 'a',
        'va_profile_item_id': communication_item.va_profile_item_id,
    }

    response = admin_request.post('communication_item.create_communication_item', post_data, 400)

    assert isinstance(response, dict) and 'errors' in response, response
    assert isinstance(response['errors'], list) and len(response['errors']) == 1
    assert isinstance(response['errors'][0], dict)
    assert 'error' in response['errors'][0]
    assert 'message' in response['errors'][0]


def test_communication_item_default_send(
    notify_db_session,
    admin_request,
):

    va_profile_id = 9876
    post_data = {'name': 'communication item default send test', 'va_profile_item_id': va_profile_id}
    response = admin_request.post('communication_item.create_communication_item', post_data, 201)

    assert response['default_send_indicator'], 'Should be True by default.'

    # Teardown
    stmt = delete(CommunicationItem).where(CommunicationItem.va_profile_item_id == va_profile_id)
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


#############
# Retrieve
#############


def test_get_all_communication_items(admin_request, sample_communication_item):
    """
    The sample_communication_item fixture ensures the table contains at least one
    row, but it might have more.
    """

    sample_communication_item()
    response = admin_request.get('communication_item.get_all_communication_items', 200)
    assert isinstance(response['data'], list)

    for communication_item in response['data']:
        assert isinstance(communication_item, dict)
        assert isinstance(communication_item['default_send_indicator'], bool)
        assert isinstance(communication_item['name'], str) and communication_item['name']
        assert isinstance(communication_item['va_profile_item_id'], int)
        assert isinstance(UUID(communication_item['id']), UUID)


def test_get_communication_item(admin_request, sample_communication_item):
    communication_item = sample_communication_item()
    response = admin_request.get(
        'communication_item.get_communication_item', 200, communication_item_id=communication_item.id
    )

    assert isinstance(response, dict), response
    assert isinstance(response['default_send_indicator'], bool)
    assert response['default_send_indicator'], 'Should be True by default.'
    assert response['name'] == communication_item.name
    assert response['va_profile_item_id'] == communication_item.va_profile_item_id
    assert response['id'] == str(communication_item.id)


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
        ({'va_profile_item_id': 'not a number'}, 400),
        ({'va_profile_item_id': -5}, 400),
        ({'va_profile_item_id': 0}, 400),
        ({'name': 'different name'}, 200),
        ({'default_send_indicator': False}, 200),
    ],
)
def test_partially_update_communication_item(admin_request, post_data, expected_status, sample_communication_item):
    communication_item = sample_communication_item()
    response = admin_request.patch(
        'communication_item.partially_update_communication_item',
        post_data,
        expected_status,
        communication_item_id=str(communication_item.id),
    )

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


def test_delete_communication_item(notify_db_session, admin_request, sample_communication_item):
    communication_item = sample_communication_item()
    communication_item_id = communication_item.id

    admin_request.delete(
        'communication_item.delete_communication_item', 202, communication_item_id=communication_item.id
    )

    # Ensure communication_item is not in the database.
    assert notify_db_session.session.get(CommunicationItem, communication_item_id) is None


@pytest.mark.parametrize('communication_item_id', ["doesn't exist", '39247cfc-a52d-4b2b-b9a9-2ef8a20190cb'])
def test_delete_communication_item_not_found(notify_db_session, admin_request, communication_item_id):
    response = admin_request.delete(
        'communication_item.delete_communication_item', 404, communication_item_id=communication_item_id
    )

    assert isinstance(response, dict), response
