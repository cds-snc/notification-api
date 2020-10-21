from app.dao.notifications_dao import dao_delete_notification_with_recipient_identifier_by_id
from app.dao.recipient_identifiers_dao import persist_recipient_identifiers
from app.models import RecipientIdentifiers, VA_PROFILE_ID, Notification

from tests.app.db import (
    create_notification
)


def test_should_add_recipient_identifiers_to_recipient_identifiers_table(notify_api, sample_job, sample_email_template):
    notification = create_notification(to_field=None, job=sample_job, template=sample_email_template)
    notification_id = notification.id
    va_identifier = {'id_type': VA_PROFILE_ID,
                     'value': 'foo'}
    form = {
        'va_identifier': va_identifier
    }

    persist_recipient_identifiers(notification_id, form)

    assert RecipientIdentifiers.query.count() == 1
    assert RecipientIdentifiers.query.get((notification_id, va_identifier['id_type'], va_identifier['value']))\
        .notification_id == notification_id
    assert RecipientIdentifiers.query.get((notification_id, va_identifier['id_type'], va_identifier['value']))\
        .va_identifier_type == va_identifier['id_type']
    assert RecipientIdentifiers.query.get((notification_id, va_identifier['id_type'], va_identifier['value'])) \
        .va_identifier_value == va_identifier['value']

    assert notification.recipient_identifiers[va_identifier['id_type']].va_identifier_value == va_identifier['value']
    assert notification.recipient_identifiers[va_identifier['id_type']].va_identifier_type == va_identifier['id_type']


def test_should_not_persist_data_if_no_va_identifier_passed_in(notify_api, sample_job, sample_email_template):
    notification = create_notification(to_field=None, job=sample_job, template=sample_email_template)
    form = {
        'email_address': 'test@email.com'
    }

    persist_recipient_identifiers(notification.id, form)
    assert RecipientIdentifiers.query.count() == 0


def test_should_delete_recipient_identifiers_if_notification_deleted(notify_api, sample_job, sample_email_template):
    notification = create_notification(to_field=None, job=sample_job, template=sample_email_template)
    notification_id = notification.id
    va_identifier = {'id_type': VA_PROFILE_ID,
                     'value': 'foo'}
    form = {
        'va_identifier': va_identifier
    }

    persist_recipient_identifiers(notification_id, form)
    assert RecipientIdentifiers.query.get((notification_id, va_identifier['id_type'], va_identifier['value'])) \
        .notification_id == notification_id

    dao_delete_notification_with_recipient_identifier_by_id(notification_id)

    assert Notification.query.get(notification.id) is None
    assert RecipientIdentifiers.query.get((notification_id, va_identifier['id_type'], va_identifier['value'])) is None


# def test_should_add_recipient_identifiers_to_recipient_identifiers_history():
