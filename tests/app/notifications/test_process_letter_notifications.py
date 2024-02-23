import pytest
from sqlalchemy import select

from app.models import LETTER_TYPE, NOTIFICATION_CREATED, Notification
from app.notifications.process_letter_notifications import create_letter_notification


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.serial
def test_create_letter_notification_creates_notification(notify_db_session, sample_letter_template, sample_api_key):
    data = {
        'personalisation': {
            'address_line_1': 'The Queen',
            'address_line_2': 'Buckingham Palace',
            'postcode': 'SW1 1AA',
        }
    }

    notification = create_letter_notification(data, sample_letter_template, sample_api_key, NOTIFICATION_CREATED)

    stmt = select(Notification)
    assert notification == notify_db_session.session.scalars(stmt).one()
    assert notification.job is None
    assert notification.status == NOTIFICATION_CREATED
    assert notification.template_id == sample_letter_template.id
    assert notification.template_version == sample_letter_template.version
    assert notification.api_key == sample_api_key
    assert notification.notification_type == LETTER_TYPE
    assert notification.key_type == sample_api_key.key_type
    assert notification.reference is not None
    assert notification.client_reference is None
    assert notification.postage == 'second'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_create_letter_notification_sets_reference(sample_letter_template, sample_api_key):
    data = {
        'personalisation': {
            'address_line_1': 'The Queen',
            'address_line_2': 'Buckingham Palace',
            'postcode': 'SW1 1AA',
        },
        'reference': 'foo',
    }

    notification = create_letter_notification(data, sample_letter_template, sample_api_key, NOTIFICATION_CREATED)

    assert notification.client_reference == 'foo'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_create_letter_notification_sets_billable_units(sample_letter_template, sample_api_key):
    data = {
        'personalisation': {
            'address_line_1': 'The Queen',
            'address_line_2': 'Buckingham Palace',
            'postcode': 'SW1 1AA',
        },
    }

    notification = create_letter_notification(
        data, sample_letter_template, sample_api_key, NOTIFICATION_CREATED, billable_units=3
    )

    assert notification.billable_units == 3
