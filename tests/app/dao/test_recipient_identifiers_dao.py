from app.dao.recipient_identifiers_dao import persist_recipient_identifiers
from app.models import RecipientIdentifiers, VA_PROFILE_ID

from tests.app.db import (
    create_notification
)


def test_should_add_recipient_identifiers_to_recipient_identifiers_table(notify_api, sample_job, sample_email_template):
    notification = create_notification(to_field=None, job=sample_job, template=sample_email_template)
    notification_id = notification.id
    va_identifier_type = VA_PROFILE_ID
    va_identifier_value = "foo"

    persist_recipient_identifiers(notification_id, va_identifier_type, va_identifier_value)
    assert RecipientIdentifiers.query.count() == 1
    assert RecipientIdentifiers.query.get((notification_id, va_identifier_type, va_identifier_value))\
        .notification_id == notification_id
    assert RecipientIdentifiers.query.get((notification_id, va_identifier_type, va_identifier_value))\
        .va_identifier_type == va_identifier_type
    assert RecipientIdentifiers.query.get((notification_id, va_identifier_type, va_identifier_value)) \
        .va_identifier_value == va_identifier_value


# def test_should_add_recipient_identifiers_to_recipient_identifiers_history():

# def test_should_have_access_to_recipient_identifiers_dict_from_notification():
