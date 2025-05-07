import pytest
from random import randint

from freezegun import freeze_time
from sqlalchemy.exc import IntegrityError

from app import encryption
from app.constants import (
    SMS_TYPE,
    MOBILE_TYPE,
    EMAIL_TYPE,
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_SENDING,
    NOTIFICATION_PENDING,
    NOTIFICATION_FAILED,
    NOTIFICATION_STATUS_LETTER_ACCEPTED,
    NOTIFICATION_STATUS_LETTER_RECEIVED,
    NOTIFICATION_STATUS_TYPES_FAILED,
    COMPLAINT_CALLBACK_TYPE,
    QUEUE_CHANNEL_TYPE,
    WEBHOOK_CHANNEL_TYPE,
)
from app.models import (
    ServiceCallback,
    ServiceWhitelist,
    Notification,
)
from app.va.identifier import IdentifierType


@pytest.mark.parametrize('mobile_number', ['650 253 2222', '+1 650 253 2222'])
def test_should_build_service_whitelist_from_mobile_number(mobile_number):
    service_whitelist = ServiceWhitelist.from_string('service_id', MOBILE_TYPE, mobile_number)

    assert service_whitelist.recipient == mobile_number


@pytest.mark.parametrize('email_address', ['test@example.com'])
def test_should_build_service_whitelist_from_email_address(email_address):
    service_whitelist = ServiceWhitelist.from_string('service_id', EMAIL_TYPE, email_address)

    assert service_whitelist.recipient == email_address


@pytest.mark.parametrize(
    'contact, recipient_type', [('', None), ('07700dsadsad', MOBILE_TYPE), ('gmail.com', EMAIL_TYPE)]
)
def test_should_not_build_service_whitelist_from_invalid_contact(recipient_type, contact):
    with pytest.raises(ValueError):
        ServiceWhitelist.from_string('service_id', recipient_type, contact)


@pytest.mark.parametrize(
    'initial_statuses, expected_statuses',
    [
        # passing in single statuses as strings
        (NOTIFICATION_FAILED, NOTIFICATION_STATUS_TYPES_FAILED),
        (NOTIFICATION_STATUS_LETTER_ACCEPTED, (NOTIFICATION_SENDING, NOTIFICATION_CREATED)),
        (NOTIFICATION_CREATED, (NOTIFICATION_CREATED,)),
        # passing in tuples containing single statuses
        ((NOTIFICATION_FAILED,), NOTIFICATION_STATUS_TYPES_FAILED),
        ((NOTIFICATION_CREATED,), (NOTIFICATION_CREATED,)),
        (NOTIFICATION_STATUS_LETTER_RECEIVED, NOTIFICATION_DELIVERED),
        # passing in tuples containing multiple statuses
        ((NOTIFICATION_FAILED, NOTIFICATION_CREATED), (*NOTIFICATION_STATUS_TYPES_FAILED, NOTIFICATION_CREATED)),
        ((NOTIFICATION_CREATED, NOTIFICATION_PENDING), (NOTIFICATION_CREATED, NOTIFICATION_PENDING)),
        (
            (NOTIFICATION_FAILED, NOTIFICATION_STATUS_LETTER_ACCEPTED),
            (*NOTIFICATION_STATUS_TYPES_FAILED, NOTIFICATION_SENDING, NOTIFICATION_CREATED),
        ),
        # checking we don't end up with duplicates
        (
            (NOTIFICATION_FAILED, NOTIFICATION_CREATED),
            (*NOTIFICATION_STATUS_TYPES_FAILED, NOTIFICATION_CREATED),
        ),
    ],
)
def test_status_conversion(initial_statuses, expected_statuses):
    converted_statuses = Notification.substitute_status(initial_statuses)
    assert len(converted_statuses) == len(expected_statuses)
    assert set(converted_statuses) == set(expected_statuses)


@freeze_time('2017-03-26 23:01:53.321312')
def test_notification_for_csv_returns_est_correctly(
    notify_api,
    sample_template,
    sample_notification,
):
    notification = sample_notification(template=sample_template())

    serialized = notification.serialize_for_csv()
    assert serialized['created_at'] == '2017-03-26 19:01:53'


def test_notification_personalisation_getter_returns_empty_dict_from_None():
    noti = Notification()
    noti._personalisation = None
    assert noti.personalisation == {}


def test_notification_personalisation_getter_always_returns_empty_dict(notify_api):
    noti = Notification()
    noti._personalisation = encryption.encrypt({})
    assert noti.personalisation == {}


@pytest.mark.parametrize('input_value', [None, {}])
def test_notification_personalisation_setter_always_sets_empty_dict(notify_api, input_value):
    noti = Notification()
    noti.personalisation = input_value

    assert noti._personalisation == encryption.encrypt({})


def test_notification_subject_is_none_for_sms():
    assert Notification(notification_type=SMS_TYPE).subject is None


def test_notification_subject_fills_in_placeholders(
    notify_api,
    sample_template,
    sample_notification,
):
    template = sample_template(template_type=EMAIL_TYPE, subject='((name))')
    notification = sample_notification(template=template, personalisation={'name': 'hello'})
    assert notification.subject == '<redacted>'


def test_notification_serializes_created_by_name_with_no_created_by_id(client, sample_notification):
    res = sample_notification(created_by_id=None).serialize()
    assert res['created_by_name'] is None


def test_notification_serializes_created_by_name_with_created_by_id(client, sample_notification, sample_user):
    user = sample_user()
    notification = sample_notification()
    notification.created_by_id = user.id
    res = notification.serialize()
    assert res['created_by_name'] == user.name


def test_sms_notification_serializes_without_subject(client, sample_template):
    res = sample_template().serialize()
    assert res['subject'] is None


def test_email_notification_serializes_with_subject(client, sample_template):
    res = sample_template(template_type=EMAIL_TYPE).serialize()
    assert res['subject'] == 'Subject'


def test_user_service_role_serializes_without_updated(client, sample_user_service_role):
    res = sample_user_service_role.serialize()
    assert res['id'] is not None
    assert res['role'] == 'admin'
    assert res['user_id'] == str(sample_user_service_role.user_id)
    assert res['service_id'] == str(sample_user_service_role.service_id)
    assert res['updated_at'] is None


def test_user_service_role_serializes_with_updated(client, sample_service_role_udpated):
    res = sample_service_role_udpated.serialize()
    assert res['id'] is not None
    assert res['role'] == 'admin'
    assert res['user_id'] == str(sample_service_role_udpated.user_id)
    assert res['service_id'] == str(sample_service_role_udpated.service_id)
    assert res['updated_at'] == sample_service_role_udpated.updated_at.isoformat() + 'Z'


def test_notification_references_template_history(
    client,
    notify_api,
    sample_template,
    sample_notification,
):
    template = sample_template()
    notification = sample_notification(template=template)
    template.version = 3
    template.content = 'New template content'

    res = notification.serialize()
    assert res['template']['version'] == 1

    assert res['body'] == notification.template.content
    assert notification.template.content != template.content


def test_email_notification_serializes_with_recipient_identifiers(
    client,
    sample_template,
    sample_notification,
):
    recipient_identifiers = [
        {'id_type': IdentifierType.VA_PROFILE_ID.value, 'id_value': 'some vaprofileid'},
        {'id_type': IdentifierType.ICN.value, 'id_value': 'some icn'},
    ]

    template = sample_template(template_type=EMAIL_TYPE)
    notification = sample_notification(template=template, recipient_identifiers=recipient_identifiers)

    serialized_recipient_identifiers = notification.serialize()['recipient_identifiers']

    recipient_identifiers[1]['id_value'] = '<redacted>'
    assert serialized_recipient_identifiers == recipient_identifiers


def test_email_notification_serializes_with_empty_recipient_identifiers(
    client,
    sample_template,
    sample_notification,
):
    notifcation = sample_notification(template=sample_template(template_type=EMAIL_TYPE))
    response = notifcation.serialize()
    assert response['recipient_identifiers'] == []


def test_notification_requires_a_valid_template_version(client, sample_template, sample_notification):
    template = sample_template()
    template.version = 2
    with pytest.raises(IntegrityError):
        sample_notification(template=template)


def test_inbound_number_serializes_with_service(client, sample_inbound_number, sample_service):
    service = sample_service()
    inbound_number = sample_inbound_number(number=str(randint(1, 999999999)), service_id=service.id)
    serialized_inbound_number = inbound_number.serialize()
    assert serialized_inbound_number.get('id') == str(inbound_number.id)
    assert serialized_inbound_number.get('service').get('id') == str(inbound_number.service.id)
    assert serialized_inbound_number.get('service').get('name') == inbound_number.service.name


def test_inbound_number_returns_inbound_number(client, sample_service, sample_inbound_number):
    service = sample_service()
    inbound_number = sample_inbound_number(number=str(randint(1, 999999999)), service_id=service.id)

    assert inbound_number in service.inbound_numbers


def test_inbound_number_returns_none_when_no_inbound_number(client, sample_service):
    service = sample_service()

    assert service.inbound_numbers == []


def test_service_get_default_sms_sender(sample_service):
    service = sample_service()
    assert service.get_default_sms_sender() == 'testing'


def test_login_event_serialization(sample_login_event):
    login_event = sample_login_event()

    json = login_event.serialize()
    assert json['data'] == login_event.data
    assert json['created_at']
