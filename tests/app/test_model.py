import pytest
from freezegun import freeze_time
from sqlalchemy.exc import IntegrityError

from app import signer_personalisation
from app.models import (
    BULK,
    EMAIL_TYPE,
    MOBILE_TYPE,
    NORMAL,
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_FAILED,
    NOTIFICATION_PENDING,
    NOTIFICATION_SENDING,
    NOTIFICATION_STATUS_LETTER_ACCEPTED,
    NOTIFICATION_STATUS_LETTER_RECEIVED,
    NOTIFICATION_STATUS_TYPES_FAILED,
    NOTIFICATION_TECHNICAL_FAILURE,
    PRECOMPILED_TEMPLATE_NAME,
    PRIORITY,
    SMS_TYPE,
    Notification,
    ServiceSafelist,
)
from tests.app.conftest import create_template_category
from tests.app.db import (
    create_inbound_number,
    create_letter_contact,
    create_notification,
    create_reply_to_email,
    create_service,
    create_template,
    create_template_folder,
    save_notification,
)


@pytest.mark.parametrize("mobile_number", ["650 253 2222", "+1 650 253 2222"])
def test_should_build_service_safelist_from_mobile_number(mobile_number):
    service_safelist = ServiceSafelist.from_string("service_id", MOBILE_TYPE, mobile_number)

    assert service_safelist.recipient == mobile_number


@pytest.mark.parametrize("email_address", ["test@example.com"])
def test_should_build_service_safelist_from_email_address(email_address):
    service_safelist = ServiceSafelist.from_string("service_id", EMAIL_TYPE, email_address)

    assert service_safelist.recipient == email_address


@pytest.mark.parametrize(
    "contact, recipient_type",
    [("", None), ("07700dsadsad", MOBILE_TYPE), ("gmail.com", EMAIL_TYPE)],
)
def test_should_not_build_service_safelist_from_invalid_contact(recipient_type, contact):
    with pytest.raises(ValueError):
        ServiceSafelist.from_string("service_id", recipient_type, contact)


@pytest.mark.parametrize(
    "initial_statuses, expected_statuses",
    [
        # passing in single statuses as strings
        (NOTIFICATION_FAILED, NOTIFICATION_STATUS_TYPES_FAILED),
        (
            NOTIFICATION_STATUS_LETTER_ACCEPTED,
            [NOTIFICATION_SENDING, NOTIFICATION_CREATED],
        ),
        (NOTIFICATION_CREATED, [NOTIFICATION_CREATED]),
        (NOTIFICATION_TECHNICAL_FAILURE, [NOTIFICATION_TECHNICAL_FAILURE]),
        # passing in lists containing single statuses
        ([NOTIFICATION_FAILED], NOTIFICATION_STATUS_TYPES_FAILED),
        ([NOTIFICATION_CREATED], [NOTIFICATION_CREATED]),
        ([NOTIFICATION_TECHNICAL_FAILURE], [NOTIFICATION_TECHNICAL_FAILURE]),
        (NOTIFICATION_STATUS_LETTER_RECEIVED, NOTIFICATION_DELIVERED),
        # passing in lists containing multiple statuses
        (
            [NOTIFICATION_FAILED, NOTIFICATION_CREATED],
            NOTIFICATION_STATUS_TYPES_FAILED + [NOTIFICATION_CREATED],
        ),
        (
            [NOTIFICATION_CREATED, NOTIFICATION_PENDING],
            [NOTIFICATION_CREATED, NOTIFICATION_PENDING],
        ),
        (
            [NOTIFICATION_CREATED, NOTIFICATION_TECHNICAL_FAILURE],
            [NOTIFICATION_CREATED, NOTIFICATION_TECHNICAL_FAILURE],
        ),
        (
            [NOTIFICATION_FAILED, NOTIFICATION_STATUS_LETTER_ACCEPTED],
            NOTIFICATION_STATUS_TYPES_FAILED + [NOTIFICATION_SENDING, NOTIFICATION_CREATED],
        ),
        # checking we don't end up with duplicates
        (
            [NOTIFICATION_FAILED, NOTIFICATION_CREATED, NOTIFICATION_TECHNICAL_FAILURE],
            NOTIFICATION_STATUS_TYPES_FAILED + [NOTIFICATION_CREATED],
        ),
    ],
)
def test_status_conversion(initial_statuses, expected_statuses):
    converted_statuses = Notification.substitute_status(initial_statuses)
    assert len(converted_statuses) == len(expected_statuses)
    assert set(converted_statuses) == set(expected_statuses)


@freeze_time("2016-01-01 11:09:00.000000")
@pytest.mark.parametrize(
    "template_type, recipient",
    [
        ("sms", "+16502532222"),
        ("email", "foo@bar.com"),
    ],
)
def test_notification_for_csv_returns_correct_type(sample_service, template_type, recipient):
    template = create_template(sample_service, template_type=template_type)
    notification = save_notification(create_notification(template, to_field=recipient))

    serialized = notification.serialize_for_csv()
    assert serialized["template_type"] == template_type


@freeze_time("2016-01-01 11:09:00.000000")
def test_notification_for_csv_returns_correct_job_row_number(sample_job):
    notification = save_notification(create_notification(sample_job.template, sample_job, job_row_number=0))

    serialized = notification.serialize_for_csv()
    assert serialized["row_number"] == 1


@freeze_time("2016-01-30 12:39:58.321312")
@pytest.mark.parametrize(
    "template_type, status, feedback_subtype, feedback_reason, expected_status",
    [
        ("email", "failed", None, None, "Failed"),
        ("email", "technical-failure", None, None, "Tech issue"),
        ("email", "temporary-failure", None, None, "Content or inbox issue"),
        ("email", "permanent-failure", None, None, "No such address"),
        ("email", "permanent-failure", "suppressed", None, "Blocked"),
        ("email", "permanent-failure", "on-account-suppression-list", None, "Blocked"),
        ("sms", "temporary-failure", None, None, "Carrier issue"),
        ("sms", "permanent-failure", None, None, "No such number"),
        ("sms", "provider-failure", None, "DESTINATION_COUNTRY_BLOCKED", "Can't send to this international number"),
        ("sms", "provider-failure", None, "NO_ORIGINATION_IDENTITIES_FOUND", "Can't send to this international number"),
        ("sms", "sent", None, None, "Sent"),
        ("letter", "created", None, None, "Accepted"),
        ("letter", "sending", None, None, "Accepted"),
        ("letter", "technical-failure", None, None, "Technical failure"),
        ("letter", "delivered", None, None, "Received"),
    ],
)
def test_notification_for_csv_returns_formatted_status_ff_bouncerate(
    sample_service, template_type, status, feedback_subtype, feedback_reason, expected_status
):
    template = create_template(sample_service, template_type=template_type)
    notification = save_notification(create_notification(template, status=status))
    if feedback_subtype:
        notification.feedback_subtype = feedback_subtype
    if feedback_reason:
        notification.feedback_reason = feedback_reason

    serialized = notification.serialize_for_csv()
    assert serialized["status"] == expected_status


@freeze_time("2017-03-26 23:01:53.321312")
def test_notification_for_csv_returns_est_correctly(sample_template):
    notification = save_notification(create_notification(sample_template))

    serialized = notification.serialize_for_csv()
    assert serialized["created_at"] == "2017-03-26 19:01:53"


def test_notification_personalisation_getter_returns_empty_dict_from_None():
    noti = Notification()
    noti._personalisation = None
    assert noti.personalisation == {}


def test_notification_personalisation_getter_always_returns_empty_dict():
    noti = Notification()
    noti._personalisation = signer_personalisation.sign({})
    assert noti.personalisation == {}


@pytest.mark.parametrize("input_value", [None, {}])
def test_notification_personalisation_setter_always_sets_empty_dict(input_value):
    noti = Notification()
    noti.personalisation = input_value

    assert noti._personalisation == signer_personalisation.sign({})


def test_notification_subject_is_none_for_sms():
    assert Notification(notification_type=SMS_TYPE).subject is None


@pytest.mark.parametrize("template_type", ["email", "letter"])
def test_notification_subject_fills_in_placeholders(sample_service, template_type):
    template = create_template(service=sample_service, template_type=template_type, subject="((name))")
    notification = save_notification(create_notification(template=template, personalisation={"name": "hello"}))
    assert notification.subject == "hello"


def test_letter_notification_serializes_with_address(client, sample_letter_notification):
    sample_letter_notification.personalisation = {
        "address_line_1": "foo",
        "address_line_3": "bar",
        "address_line_5": None,
        "postcode": "SW1 1AA",
    }
    res = sample_letter_notification.serialize()
    assert res["line_1"] == "foo"
    assert res["line_2"] is None
    assert res["line_3"] == "bar"
    assert res["line_4"] is None
    assert res["line_5"] is None
    assert res["line_6"] is None
    assert res["postcode"] == "SW1 1AA"


def test_notification_serializes_created_by_name_with_no_created_by_id(client, sample_notification):
    res = sample_notification.serialize()
    assert res["created_by_name"] is None


def test_notification_serializes_created_by_name_with_created_by_id(client, sample_notification, sample_user):
    sample_notification.created_by_id = sample_user.id
    res = sample_notification.serialize()
    assert res["created_by_name"] == sample_user.name


def test_sms_notification_serializes_without_subject(client, sample_template):
    res = sample_template.serialize()
    assert res["subject"] is None


def test_email_notification_serializes_with_subject(client, sample_email_template):
    res = sample_email_template.serialize()
    assert res["subject"] == "Email Subject"


def test_letter_notification_serializes_with_subject(client, sample_letter_template):
    res = sample_letter_template.serialize()
    assert res["subject"] == "Template subject"


def test_notification_references_template_history(client, sample_template):
    noti = save_notification(create_notification(sample_template))
    sample_template.version = 3
    sample_template.content = "New template content"

    res = noti.serialize()
    assert res["template"]["version"] == 1

    assert res["body"] == noti.template.content
    assert noti.template.content != sample_template.content


def test_notification_requires_a_valid_template_version(client, sample_template):
    sample_template.version = 2
    with pytest.raises(IntegrityError):
        save_notification(create_notification(sample_template))


def test_inbound_number_serializes_with_service(client, notify_db_session):
    service = create_service()
    inbound_number = create_inbound_number(number="1", service_id=service.id)
    serialized_inbound_number = inbound_number.serialize()
    assert serialized_inbound_number.get("id") == str(inbound_number.id)
    assert serialized_inbound_number.get("service").get("id") == str(inbound_number.service.id)
    assert serialized_inbound_number.get("service").get("name") == inbound_number.service.name


def test_inbound_number_returns_inbound_number(client, notify_db_session):
    service = create_service()
    inbound_number = create_inbound_number(number="1", service_id=service.id)

    assert service.get_inbound_number() == inbound_number.number


def test_inbound_number_returns_none_when_no_inbound_number(client, notify_db_session):
    service = create_service()

    assert not service.get_inbound_number()


def test_service_get_default_reply_to_email_address(sample_service):
    create_reply_to_email(service=sample_service, email_address="default@email.com")

    assert sample_service.get_default_reply_to_email_address() == "default@email.com"


def test_service_get_default_contact_letter(sample_service):
    create_letter_contact(service=sample_service, contact_block="London,\nNW1A 1AA")

    assert sample_service.get_default_letter_contact() == "London,\nNW1A 1AA"


def test_service_get_default_sms_sender(notify_db_session):
    service = create_service()
    assert service.get_default_sms_sender() == "testing"


def test_letter_notification_serializes_correctly(client, sample_letter_notification):
    sample_letter_notification.personalisation = {
        "addressline1": "test",
        "addressline2": "London",
        "postcode": "N1",
    }

    json = sample_letter_notification.serialize()
    assert json["line_1"] == "test"
    assert json["line_2"] == "London"
    assert json["postcode"] == "N1"


def test_letter_notification_postcode_can_be_null_for_precompiled_letters(client, sample_letter_notification):
    sample_letter_notification.personalisation = {
        "address_line_1": "test",
        "address_line_2": "London",
    }

    json = sample_letter_notification.serialize()
    assert json["line_1"] == "test"
    assert json["line_2"] == "London"
    assert json["postcode"] is None


def test_is_precompiled_letter_false(sample_letter_template):
    assert not sample_letter_template.is_precompiled_letter


def test_is_precompiled_letter_true(sample_letter_template):
    sample_letter_template.hidden = True
    sample_letter_template.name = PRECOMPILED_TEMPLATE_NAME
    assert sample_letter_template.is_precompiled_letter


def test_is_precompiled_letter_hidden_true_not_name(sample_letter_template):
    sample_letter_template.hidden = True
    assert not sample_letter_template.is_precompiled_letter


def test_is_precompiled_letter_name_correct_not_hidden(sample_letter_template):
    sample_letter_template.name = PRECOMPILED_TEMPLATE_NAME
    assert not sample_letter_template.is_precompiled_letter


def test_template_folder_is_parent(sample_service):
    x = None
    folders = []
    for i in range(5):
        x = create_template_folder(sample_service, name=str(i), parent=x)
        folders.append(x)

    assert folders[0].is_parent_of(folders[1])
    assert folders[0].is_parent_of(folders[2])
    assert folders[0].is_parent_of(folders[4])
    assert folders[1].is_parent_of(folders[2])
    assert not folders[1].is_parent_of(folders[0])


class TestTemplateProcessType:
    @pytest.mark.parametrize(
        "template_type, process_type, sms_process_type, email_process_type, expected_template_process_type",
        [
            (SMS_TYPE, None, NORMAL, BULK, NORMAL),
            (EMAIL_TYPE, None, BULK, NORMAL, NORMAL),
            (SMS_TYPE, BULK, PRIORITY, PRIORITY, BULK),
            (EMAIL_TYPE, BULK, PRIORITY, PRIORITY, BULK),
        ],
    )
    def test_template_process_type(
        self,
        notify_db,
        notify_db_session,
        template_type,
        process_type,
        sms_process_type,
        email_process_type,
        expected_template_process_type,
    ):
        template_category = create_template_category(
            notify_db, notify_db_session, sms_process_type=sms_process_type, email_process_type=email_process_type
        )
        template = create_template(
            service=create_service(), template_type=template_type, process_type=process_type, template_category=template_category
        )
        assert template.process_type_column == process_type
        assert template.process_type == expected_template_process_type


def test_fido2_key_serialization(sample_fido2_key):
    json = sample_fido2_key.serialize()
    assert json["name"] == sample_fido2_key.name
    assert json["created_at"]


def test_login_event_serialization(sample_login_event):
    json = sample_login_event.serialize()
    assert json["data"] == sample_login_event.data
    assert json["created_at"]


class TestNotificationModel:
    def test_queue_name_in_notifications(self, sample_service):
        template = create_template(sample_service, template_type="email")
        notification = save_notification(create_notification(template, to_field="test@example.com", queue_name="tester"))
        assert notification.queue_name == "tester"
