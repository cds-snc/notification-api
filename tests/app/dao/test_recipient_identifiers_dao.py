import pytest

from app.dao.notifications_dao import dao_delete_notification_by_id
from app.dao.recipient_identifiers_dao import persist_recipient_identifiers
from app.models import RecipientIdentifier, VA_PROFILE_ID, Notification, ICN, PID

from tests.app.db import (
    create_notification
)


@pytest.mark.parametrize('id_type, value',
                         [(VA_PROFILE_ID, 'some va profile id'),
                          (PID, 'some pid'),
                          (ICN, 'some icn')])
def test_should_add_recipient_identifiers_to_recipient_identifiers_table(
        notify_api,
        sample_job,
        sample_email_template,
        id_type,
        value
):
    notification = create_notification(to_field=None, job=sample_job, template=sample_email_template)
    notification_id = notification.id
    form = {
        'va_identifier': {'id_type': id_type,
                          'value': value}
    }

    persist_recipient_identifiers(notification_id, form)

    assert RecipientIdentifier.query.count() == 1
    assert RecipientIdentifier.query.get((notification_id, id_type, value)) \
        .notification_id == notification_id
    assert RecipientIdentifier.query.get((notification_id, id_type, value)) \
        .va_identifier_type == id_type
    assert RecipientIdentifier.query.get((notification_id, id_type, value)) \
        .va_identifier_value == value

    assert notification.recipient_identifiers[id_type].va_identifier_value == value
    assert notification.recipient_identifiers[id_type].va_identifier_type == id_type


def test_should_persist_identifiers_with_the_same_notification_id(notify_api, sample_job, sample_email_template):
    notification = create_notification(to_field=None, job=sample_job, template=sample_email_template)
    notification_id = notification.id
    icn_form = {
        'va_identifier': {
            'id_type': ICN,
            'value': 'some icn'
        }
    }
    va_profile_id_form = {
        'va_identifier': {
            'id_type': VA_PROFILE_ID,
            'value': 'some va profile id'
        }
    }

    persist_recipient_identifiers(notification_id, icn_form)
    persist_recipient_identifiers(notification_id, va_profile_id_form)
    assert RecipientIdentifier.query.count() == 2

    assert RecipientIdentifier.query.get(
        (notification_id, icn_form['va_identifier']['id_type'], icn_form['va_identifier']['value']))
    assert RecipientIdentifier.query.get(
        (notification_id, va_profile_id_form['va_identifier']['id_type'], va_profile_id_form['va_identifier']['value']))


def test_should_not_persist_data_if_no_va_identifier_passed_in(notify_api, sample_job, sample_email_template):
    notification = create_notification(to_field=None, job=sample_job, template=sample_email_template)
    form = {
        'email_address': 'test@email.com'
    }

    persist_recipient_identifiers(notification.id, form)
    assert RecipientIdentifier.query.count() == 0


def test_should_delete_recipient_identifiers_if_notification_deleted(notify_api, sample_job, sample_email_template):
    notification = create_notification(to_field=None, job=sample_job, template=sample_email_template)
    notification_id = notification.id
    va_identifier = {'id_type': VA_PROFILE_ID,
                     'value': 'foo'}
    form = {
        'va_identifier': va_identifier
    }

    persist_recipient_identifiers(notification_id, form)
    assert RecipientIdentifier.query.get((notification_id, va_identifier['id_type'], va_identifier['value'])) \
        .notification_id == notification_id

    dao_delete_notification_by_id(notification_id)

    assert Notification.query.get(notification.id) is None
    assert RecipientIdentifier.query.get((notification_id, va_identifier['id_type'], va_identifier['value'])) is None
