import datetime
import uuid

import pytest
from boto3.exceptions import Boto3Error
from sqlalchemy.exc import SQLAlchemyError
from freezegun import freeze_time
from collections import namedtuple

from app.celery import letters_pdf_tasks
from app.celery.lookup_recipient_communication_permissions_task import lookup_recipient_communication_permissions
from app.celery.contact_information_tasks import lookup_contact_info
from app.celery.lookup_va_profile_id_task import lookup_va_profile_id
from app.celery.onsite_notification_tasks import send_va_onsite_notification_task
from app.celery.provider_tasks import deliver_email, deliver_sms
from app.feature_flags import FeatureFlag
from app.models import (
    Notification,
    NotificationHistory,
    ScheduledNotification,
    Template,
    LETTER_TYPE,
    EMAIL_TYPE,
    SMS_TYPE,
    RecipientIdentifier)
from app.notifications.process_notifications import (
    create_content_for_notification,
    persist_notification,
    persist_scheduled_notification,
    send_notification_to_queue,
    simulated_recipient,
    send_to_queue_for_recipient_info_based_on_recipient_identifier)
from notifications_utils.recipients import validate_and_format_phone_number, validate_and_format_email_address
from app.v2.errors import BadRequestError
from app.va.identifier import IdentifierType


from tests.app.db import create_service, create_template
from tests.app.factories.feature_flag import mock_feature_flag


def test_create_content_for_notification_passes(sample_email_template):
    template = Template.query.get(sample_email_template.id)
    content = create_content_for_notification(template, None)
    assert str(content) == template.content


def test_create_content_for_notification_with_placeholders_passes(sample_template_with_placeholders):
    template = Template.query.get(sample_template_with_placeholders.id)
    content = create_content_for_notification(template, {'name': 'Bobby'})
    assert content.content == template.content
    assert 'Bobby' in str(content)


def test_create_content_for_notification_fails_with_missing_personalisation(sample_template_with_placeholders):
    template = Template.query.get(sample_template_with_placeholders.id)
    with pytest.raises(BadRequestError):
        create_content_for_notification(template, None)


def test_create_content_for_notification_allows_additional_personalisation(sample_template_with_placeholders):
    template = Template.query.get(sample_template_with_placeholders.id)
    create_content_for_notification(template, {'name': 'Bobby', 'Additional placeholder': 'Data'})


@freeze_time("2016-01-01 11:09:00.061258")
def test_persist_notification_creates_and_save_to_db(sample_template, sample_api_key, sample_job, mocker):
    mocked_redis = mocker.patch('app.notifications.process_notifications.redis_store.get')

    assert Notification.query.count() == 0
    assert NotificationHistory.query.count() == 0
    notification = persist_notification(
        template_id=sample_template.id,
        template_version=sample_template.version,
        recipient='+16502532222',
        service=sample_template.service,
        personalisation={},
        notification_type='sms',
        api_key_id=sample_api_key.id,
        key_type=sample_api_key.key_type,
        job_id=sample_job.id,
        job_row_number=100,
        reference="ref",
        reply_to_text=sample_template.service.get_default_sms_sender(),
        billing_code='1234567890')

    assert Notification.query.get(notification.id) is not None

    notification_from_db = Notification.query.one()

    assert notification_from_db.id == notification.id
    assert notification_from_db.template_id == notification.template_id
    assert notification_from_db.template_version == notification.template_version
    assert notification_from_db.api_key_id == notification.api_key_id
    assert notification_from_db.key_type == notification.key_type
    assert notification_from_db.key_type == notification.key_type
    assert notification_from_db.billable_units == notification.billable_units
    assert notification_from_db.notification_type == notification.notification_type
    assert notification_from_db.created_at == notification.created_at
    assert not notification_from_db.sent_at
    assert notification_from_db.updated_at == notification.updated_at
    assert notification_from_db.status == notification.status
    assert notification_from_db.reference == notification.reference
    assert notification_from_db.client_reference == notification.client_reference
    assert notification_from_db.created_by_id == notification.created_by_id
    assert notification_from_db.reply_to_text == sample_template.service.get_default_sms_sender()
    assert notification_from_db.billing_code == notification.billing_code

    mocked_redis.assert_called_once_with(str(sample_template.service_id) + "-2016-01-01-count")


def test_persist_notification_throws_exception_when_missing_template(sample_api_key):
    assert Notification.query.count() == 0
    assert NotificationHistory.query.count() == 0
    with pytest.raises(SQLAlchemyError):
        persist_notification(template_id=None,
                             template_version=None,
                             recipient='+16502532222',
                             service=sample_api_key.service,
                             personalisation=None,
                             notification_type='sms',
                             api_key_id=sample_api_key.id,
                             key_type=sample_api_key.key_type)
    assert Notification.query.count() == 0
    assert NotificationHistory.query.count() == 0


def test_cache_is_not_incremented_on_failure_to_persist_notification(sample_api_key, mocker):
    mocked_redis = mocker.patch('app.redis_store.get')
    mock_service_template_cache = mocker.patch('app.redis_store.get_all_from_hash')
    with pytest.raises(SQLAlchemyError):
        persist_notification(template_id=None,
                             template_version=None,
                             recipient='+16502532222',
                             service=sample_api_key.service,
                             personalisation=None,
                             notification_type='sms',
                             api_key_id=sample_api_key.id,
                             key_type=sample_api_key.key_type)
    mocked_redis.assert_not_called()
    mock_service_template_cache.assert_not_called()


def test_persist_notification_does_not_increment_cache_if_test_key(
        sample_template, sample_job, mocker, sample_test_api_key
):
    mocker.patch('app.notifications.process_notifications.redis_store.get', return_value="cache")
    mocker.patch('app.notifications.process_notifications.redis_store.get_all_from_hash', return_value="cache")
    daily_limit_cache = mocker.patch('app.notifications.process_notifications.redis_store.incr')
    template_usage_cache = mocker.patch('app.notifications.process_notifications.redis_store.increment_hash_value')

    assert Notification.query.count() == 0
    assert NotificationHistory.query.count() == 0
    persist_notification(
        template_id=sample_template.id,
        template_version=sample_template.version,
        recipient='+16502532222',
        service=sample_template.service,
        personalisation={},
        notification_type='sms',
        api_key_id=sample_test_api_key.id,
        key_type=sample_test_api_key.key_type,
        job_id=sample_job.id,
        job_row_number=100,
        reference="ref",
    )

    assert Notification.query.count() == 1

    assert not daily_limit_cache.called
    assert not template_usage_cache.called


@freeze_time("2016-01-01 11:09:00.061258")
def test_persist_notification_with_optionals(sample_job, sample_api_key, mocker):
    assert Notification.query.count() == 0
    assert NotificationHistory.query.count() == 0
    mocked_redis = mocker.patch('app.notifications.process_notifications.redis_store.get')
    n_id = uuid.uuid4()
    created_at = datetime.datetime(2016, 11, 11, 16, 8, 18)
    persist_notification(
        template_id=sample_job.template.id,
        template_version=sample_job.template.version,
        recipient='+16502532222',
        service=sample_job.service,
        personalisation=None,
        notification_type='sms',
        api_key_id=sample_api_key.id,
        key_type=sample_api_key.key_type,
        created_at=created_at,
        job_id=sample_job.id,
        job_row_number=10,
        client_reference="ref from client",
        notification_id=n_id,
        created_by_id=sample_job.created_by_id
    )
    assert Notification.query.count() == 1
    assert NotificationHistory.query.count() == 0
    persisted_notification = Notification.query.all()[0]
    assert persisted_notification.id == n_id
    persisted_notification.job_id == sample_job.id
    assert persisted_notification.job_row_number == 10
    assert persisted_notification.created_at == created_at
    mocked_redis.assert_called_once_with(str(sample_job.service_id) + "-2016-01-01-count")
    assert persisted_notification.client_reference == "ref from client"
    assert persisted_notification.reference is None
    assert persisted_notification.international is False
    assert persisted_notification.phone_prefix == '1'
    assert persisted_notification.rate_multiplier == 1
    assert persisted_notification.created_by_id == sample_job.created_by_id
    assert not persisted_notification.reply_to_text


@freeze_time("2016-01-01 11:09:00.061258")
def test_persist_notification_doesnt_touch_cache_for_old_keys_that_dont_exist(sample_template, sample_api_key, mocker):
    mock_incr = mocker.patch('app.notifications.process_notifications.redis_store.incr')
    mocker.patch('app.notifications.process_notifications.redis_store.get', return_value=None)
    mocker.patch('app.notifications.process_notifications.redis_store.get_all_from_hash', return_value=None)

    persist_notification(
        template_id=sample_template.id,
        template_version=sample_template.version,
        recipient='+16502532222',
        service=sample_template.service,
        personalisation={},
        notification_type='sms',
        api_key_id=sample_api_key.id,
        key_type=sample_api_key.key_type,
        reference="ref"
    )
    mock_incr.assert_not_called()


@freeze_time("2016-01-01 11:09:00.061258")
def test_persist_notification_increments_cache_if_key_exists(sample_template, sample_api_key, mocker):
    mock_incr = mocker.patch('app.notifications.process_notifications.redis_store.incr')
    mocker.patch('app.notifications.process_notifications.redis_store.get', return_value=1)
    mocker.patch('app.notifications.process_notifications.redis_store.get_all_from_hash',
                 return_value={sample_template.id, 1})

    persist_notification(
        template_id=sample_template.id,
        template_version=sample_template.version,
        recipient='+16502532222',
        service=sample_template.service,
        personalisation={},
        notification_type='sms',
        api_key_id=sample_api_key.id,
        key_type=sample_api_key.key_type,
        reference="ref2")

    mock_incr.assert_called_once_with(str(sample_template.service_id) + "-2016-01-01-count", )


@pytest.mark.parametrize((
    'research_mode, requested_queue, notification_type, key_type, expected_queue, expected_tasks'
), [
    (True, None, 'sms', 'normal', 'research-mode-tasks', [deliver_sms]),
    (True, None, 'email', 'normal', 'research-mode-tasks', [deliver_email]),
    (True, None, 'email', 'team', 'research-mode-tasks', [deliver_email]),
    (True, None, 'letter', 'normal', 'research-mode-tasks', [letters_pdf_tasks.create_letters_pdf]),
    (False, None, 'sms', 'normal', 'send-sms-tasks', [deliver_sms]),
    (False, None, 'email', 'normal', 'send-email-tasks', [deliver_email]),
    (False, None, 'sms', 'team', 'send-sms-tasks', [deliver_sms]),
    (False, None, 'letter', 'normal', 'create-letters-pdf-tasks', [letters_pdf_tasks.create_letters_pdf]),
    (False, None, 'sms', 'test', 'research-mode-tasks', [deliver_sms]),
    (True, 'notify-internal-tasks', 'email', 'normal', 'research-mode-tasks', [deliver_email]),
    (False, 'notify-internal-tasks', 'sms', 'normal', 'notify-internal-tasks', [deliver_sms]),
    (False, 'notify-internal-tasks', 'email', 'normal', 'notify-internal-tasks', [deliver_email]),
    (False, 'notify-internal-tasks', 'sms', 'test', 'research-mode-tasks', [deliver_sms]),
])
def test_send_notification_to_queue_with_no_recipient_identifiers(
    notify_db,
    notify_db_session,
    research_mode,
    requested_queue,
    notification_type,
    key_type,
    expected_queue,
    expected_tasks,
    mocker,
    sample_email_template,
    sample_sms_template_with_html,
):
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')
    template = sample_email_template if notification_type else sample_sms_template_with_html
    MockService = namedtuple('Service', ['id'])
    service = MockService(id=uuid.uuid4())

    MockSmsSender = namedtuple('ServiceSmsSender', ['service_id', 'sms_sender', 'rate_limit'])
    sms_sender = MockSmsSender(service_id=service.id, sms_sender='+18888888888', rate_limit=1)

    Notification = namedtuple('Notification', [
        'id', 'key_type', 'notification_type', 'created_at', 'template', 'service_id', 'reply_to_text'
    ])

    mocker.patch(
        'app.notifications.process_notifications.dao_get_sms_sender_by_service_id_and_number',
        return_value=None
    )

    Notification = namedtuple(
        'Notification',
        ['id', 'key_type', 'notification_type', 'created_at', 'template', 'service_id', 'reply_to_text']
    )

    MockSmsSender = namedtuple('ServiceSmsSender', ['service_id', 'sms_sender', 'rate_limit'])
    sms_sender = MockSmsSender(service_id=service.id, sms_sender='+18888888888', rate_limit=None)

    notification = Notification(
        id=uuid.uuid4(),
        key_type=key_type,
        notification_type=notification_type,
        created_at=datetime.datetime(2016, 11, 11, 16, 8, 18),
        template=template,
        service_id=service.id,
        reply_to_text=sms_sender.sms_sender
    )

    send_notification_to_queue(notification=notification, research_mode=research_mode, queue=requested_queue)

    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, expected_tasks):
        assert called_task.name == expected_task.name
        called_task_notification_arg = args[0].args[0]
        assert called_task_notification_arg == str(notification.id)


@pytest.mark.parametrize((
    'research_mode, '
    'requested_queue, '
    'notification_type, '
    'key_type, '
    'expected_queue, '
    'request_recipient_id_type, '
    'request_recipient_id_value, '
    'expected_tasks'
), [
    (
        True,
        None,
        'sms',
        'normal',
        'research-mode-tasks',
        IdentifierType.VA_PROFILE_ID.value, 'some va profile id',
        [lookup_recipient_communication_permissions, deliver_sms]
    ),
    (
        True,
        None,
        'email',
        'normal',
        'research-mode-tasks',
        IdentifierType.PID.value,
        'some pid',
        [
            lookup_va_profile_id,
            send_va_onsite_notification_task,
            lookup_recipient_communication_permissions,
            deliver_email
        ]
    ),
    (
        True,
        None,
        'email',
        'team',
        'research-mode-tasks',
        IdentifierType.ICN.value,
        'some icn',
        [
            lookup_va_profile_id,
            send_va_onsite_notification_task,
            lookup_recipient_communication_permissions,
            deliver_email
        ]
    ),
    (
        True,
        'notify-internal-tasks',
        'email',
        'normal',
        'research-mode-tasks',
        IdentifierType.VA_PROFILE_ID.value,
        'some va profile id',
        [lookup_recipient_communication_permissions, deliver_email]
    ),
    (
        False,
        None,
        'sms',
        'normal',
        'send-sms-tasks',
        IdentifierType.PID.value,
        'some pid',
        [
            lookup_va_profile_id,
            send_va_onsite_notification_task,
            lookup_recipient_communication_permissions,
            deliver_sms
        ]
    ),
    (
        False,
        None,
        'email',
        'normal',
        'send-email-tasks',
        IdentifierType.ICN.value,
        'some icn',
        [
            lookup_va_profile_id,
            send_va_onsite_notification_task,
            lookup_recipient_communication_permissions,
            deliver_email
        ]
    ),
    (
        False,
        None,
        'sms',
        'team',
        'send-sms-tasks',
        IdentifierType.VA_PROFILE_ID.value,
        'some va profile id',
        [lookup_recipient_communication_permissions, deliver_sms]
    ),
    (
        False,
        None,
        'sms',
        'test',
        'research-mode-tasks',
        IdentifierType.PID.value,
        'some pid',
        [
            lookup_va_profile_id,
            send_va_onsite_notification_task,
            lookup_recipient_communication_permissions,
            deliver_sms
        ]
    ),
    (
        False,
        'notify-internal-tasks',
        'sms',
        'normal',
        'notify-internal-tasks',
        IdentifierType.ICN.value,
        'some icn',
        [
            lookup_va_profile_id,
            send_va_onsite_notification_task,
            lookup_recipient_communication_permissions,
            deliver_sms
        ]
    ),
    (
        False,
        'notify-internal-tasks',
        'email',
        'normal',
        'notify-internal-tasks',
        IdentifierType.VA_PROFILE_ID.value,
        'some va profile id',
        [lookup_recipient_communication_permissions, deliver_email]
    ),
    (
        False,
        'notify-internal-tasks',
        'sms',
        'test',
        'research-mode-tasks',
        IdentifierType.PID.value,
        'some pid',
        [
            lookup_va_profile_id,
            send_va_onsite_notification_task,
            lookup_recipient_communication_permissions,
            deliver_sms
        ]
    ),
])
def test_send_notification_to_queue_with_recipient_identifiers(
    notify_db,
    notify_db_session,
    research_mode,
    requested_queue,
    notification_type,
    key_type,
    expected_queue,
    request_recipient_id_type,
    request_recipient_id_value,
    expected_tasks,
    mocker,
    sample_email_template,
    sample_sms_template_with_html,
):
    mocker.patch(
        'app.notifications.process_notifications.is_feature_enabled',
        return_value=True
    )
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')
    template = sample_email_template if notification_type else sample_sms_template_with_html
    MockService = namedtuple('Service', ['id'])
    service = MockService(id=uuid.uuid4())
    MockSmsSender = namedtuple('ServiceSmsSender', ['service_id', 'sms_sender', 'rate_limit'])
    sms_sender = MockSmsSender(service_id=service.id, sms_sender='+18888888888', rate_limit=None)

    mocker.patch('app.notifications.process_notifications.dao_get_sms_sender_by_service_id_and_number',
                 return_value=sms_sender)

    TestNotification = namedtuple(
        'Notification', [
            'id',
            'key_type',
            'notification_type',
            'created_at',
            'template',
            'recipient_identifiers',
            'service_id',
            'reply_to_text',
            'sms_sender'
        ]
    )
    notification_id = uuid.uuid4()
    notification = TestNotification(
        id=notification_id,
        key_type=key_type,
        notification_type=notification_type,
        created_at=datetime.datetime(2016, 11, 11, 16, 8, 18),
        template=template,
        recipient_identifiers={f"{request_recipient_id_type}": RecipientIdentifier(
            notification_id=notification_id,
            id_type=request_recipient_id_type,
            id_value=request_recipient_id_value
        )},
        service_id=service.id,
        reply_to_text=sms_sender.sms_sender,
        sms_sender=sms_sender
    )

    send_notification_to_queue(
        notification=notification,
        research_mode=research_mode,
        queue=requested_queue,
        recipient_id_type=request_recipient_id_type)

    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, expected_tasks):
        assert called_task.name == expected_task.name


def test_send_notification_to_queue_throws_exception_deletes_notification(sample_notification, mocker):
    mocker.patch(
        'app.notifications.process_notifications.is_feature_enabled',
        return_value=False
    )
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain', side_effect=Boto3Error("EXPECTED"))
    mocker.patch('app.notifications.process_notifications.dao_get_sms_sender_by_service_id_and_number')
    with pytest.raises(Boto3Error):
        send_notification_to_queue(sample_notification, False)
    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, ['send-sms-tasks']):
        assert called_task.args[0] == str(sample_notification.id)
        assert called_task.options['queue'] == expected_task

    assert Notification.query.count() == 0
    assert NotificationHistory.query.count() == 0


@pytest.mark.parametrize("to_address, notification_type, expected", [
    ("+16132532222", "sms", True),
    ("+16132532223", "sms", True),
    ("6132532222", "sms", True),
    ("simulate-delivered@notifications.va.gov", "email", True),
    ("simulate-delivered-2@notifications.va.gov", "email", True),
    ("simulate-delivered-3@notifications.va.gov", "email", True),
    ("6132532225", "sms", False),
    ("valid_email@test.com", "email", False)
])
def test_simulated_recipient(notify_api, to_address, notification_type, expected):
    """
    The values where the expected = 'research-mode' are listed in the config['SIMULATED_EMAIL_ADDRESSES']
    and config['SIMULATED_SMS_NUMBERS']. These values should result in using the research mode queue.
    SIMULATED_EMAIL_ADDRESSES = (
        'simulate-delivered@notifications.va.gov',
        'simulate-delivered-2@notifications.va.gov',
        'simulate-delivered-2@notifications.va.gov'
    )
    SIMULATED_SMS_NUMBERS = ('6132532222', '+16132532222', '+16132532223')
    """
    formatted_address = None

    if notification_type == 'email':
        formatted_address = validate_and_format_email_address(to_address)
    else:
        formatted_address = validate_and_format_phone_number(to_address)

    is_simulated_address = simulated_recipient(formatted_address, notification_type)

    assert is_simulated_address == expected


@pytest.mark.parametrize('recipient, expected_international, expected_prefix, expected_units', [
    ('6502532222', False, '1', 1),  # NA
    ('+16502532222', False, '1', 1),  # NA
    ('+79587714230', True, '7', 1),  # Russia
    ('+360623400400', True, '36', 3)]  # Hungary
)
def test_persist_notification_with_international_info_stores_correct_info(
    sample_job,
    sample_api_key,
    mocker,
    recipient,
    expected_international,
    expected_prefix,
    expected_units
):
    persist_notification(
        template_id=sample_job.template.id,
        template_version=sample_job.template.version,
        recipient=recipient,
        service=sample_job.service,
        personalisation=None,
        notification_type='sms',
        api_key_id=sample_api_key.id,
        key_type=sample_api_key.key_type,
        job_id=sample_job.id,
        job_row_number=10,
        client_reference="ref from client"
    )
    persisted_notification = Notification.query.all()[0]

    assert persisted_notification.international is expected_international
    assert persisted_notification.phone_prefix == expected_prefix
    assert persisted_notification.rate_multiplier == expected_units


def test_persist_notification_with_international_info_does_not_store_for_email(
    sample_job,
    sample_api_key,
    mocker
):
    persist_notification(
        template_id=sample_job.template.id,
        template_version=sample_job.template.version,
        recipient='foo@bar.com',
        service=sample_job.service,
        personalisation=None,
        notification_type='email',
        api_key_id=sample_api_key.id,
        key_type=sample_api_key.key_type,
        job_id=sample_job.id,
        job_row_number=10,
        client_reference="ref from client"
    )
    persisted_notification = Notification.query.all()[0]

    assert persisted_notification.international is False
    assert persisted_notification.phone_prefix is None
    assert persisted_notification.rate_multiplier is None


# This test assumes the local timezone is EST
def test_persist_scheduled_notification(sample_notification):
    persist_scheduled_notification(sample_notification.id, '2017-05-12 14:15')
    scheduled_notification = ScheduledNotification.query.all()
    assert len(scheduled_notification) == 1
    assert scheduled_notification[0].notification_id == sample_notification.id
    assert scheduled_notification[0].scheduled_for == datetime.datetime(2017, 5, 12, 18, 15)


@pytest.mark.parametrize('recipient, expected_recipient_normalised', [
    ('6502532222', '+16502532222'),
    ('  6502532223', '+16502532223'),
    ('6502532223', '+16502532223'),
])
def test_persist_sms_notification_stores_normalised_number(
    sample_job,
    sample_api_key,
    mocker,
    recipient,
    expected_recipient_normalised
):
    persist_notification(
        template_id=sample_job.template.id,
        template_version=sample_job.template.version,
        recipient=recipient,
        service=sample_job.service,
        personalisation=None,
        notification_type='sms',
        api_key_id=sample_api_key.id,
        key_type=sample_api_key.key_type,
        job_id=sample_job.id,
    )
    persisted_notification = Notification.query.all()[0]

    assert persisted_notification.to == recipient
    assert persisted_notification.normalised_to == expected_recipient_normalised


@pytest.mark.parametrize('recipient, expected_recipient_normalised', [
    ('FOO@bar.com', 'foo@bar.com'),
    ('BAR@foo.com', 'bar@foo.com')

])
def test_persist_email_notification_stores_normalised_email(
    sample_job,
    sample_api_key,
    mocker,
    recipient,
    expected_recipient_normalised
):
    persist_notification(
        template_id=sample_job.template.id,
        template_version=sample_job.template.version,
        recipient=recipient,
        service=sample_job.service,
        personalisation=None,
        notification_type='email',
        api_key_id=sample_api_key.id,
        key_type=sample_api_key.key_type,
        job_id=sample_job.id,
    )
    persisted_notification = Notification.query.all()[0]

    assert persisted_notification.to == recipient
    assert persisted_notification.normalised_to == expected_recipient_normalised


@pytest.mark.parametrize(
    "postage_argument, template_postage, expected_postage",
    [
        ("second", "first", "second"),
        ("first", "first", "first"),
        ("first", "second", "first"),
        (None, "second", "second")
    ]
)
def test_persist_letter_notification_finds_correct_postage(
    mocker,
    postage_argument,
    template_postage,
    expected_postage,
    sample_service_full_permissions,
    sample_api_key,
):
    template = create_template(sample_service_full_permissions, template_type=LETTER_TYPE, postage=template_postage)
    mocker.patch('app.dao.templates_dao.dao_get_template_by_id', return_value=template)
    persist_notification(
        template_id=template.id,
        template_version=template.version,
        template_postage=template.postage,
        recipient="Jane Doe, 10 Downing Street, London",
        service=sample_service_full_permissions,
        personalisation=None,
        notification_type=LETTER_TYPE,
        api_key_id=sample_api_key.id,
        key_type=sample_api_key.key_type,
        postage=postage_argument
    )
    persisted_notification = Notification.query.all()[0]

    assert persisted_notification.postage == expected_postage


def test_persist_notification_with_billable_units_stores_correct_info(
    mocker
):
    service = create_service(service_permissions=[LETTER_TYPE])
    template = create_template(service, template_type=LETTER_TYPE)
    mocker.patch('app.dao.templates_dao.dao_get_template_by_id', return_value=template)
    persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient="123 Main Street",
        service=template.service,
        personalisation=None,
        notification_type=template.template_type,
        api_key_id=None,
        key_type="normal",
        billable_units=3,
        template_postage=template.postage
    )
    persisted_notification = Notification.query.all()[0]

    assert persisted_notification.billable_units == 3


@pytest.mark.parametrize('notification_type', [
    EMAIL_TYPE,
    SMS_TYPE,
])
@pytest.mark.parametrize('id_type, id_value',
                         [(IdentifierType.VA_PROFILE_ID.value, 'some va profile id'),
                          (IdentifierType.PID.value, 'some pid'),
                          (IdentifierType.ICN.value, 'some icn')])
def test_persist_notification_persists_recipient_identifiers(
        notify_db,
        notification_type,
        id_type,
        id_value,
        sample_job,
        sample_api_key,
        mocker
):
    mocker.patch(
        'app.notifications.process_notifications.accept_recipient_identifiers_enabled',
        return_value=True
    )
    recipient_identifier = {'id_type': id_type, 'id_value': id_value}
    notification = persist_notification(
        template_id=sample_job.template.id,
        template_version=sample_job.template.version,
        service=sample_job.service,
        personalisation=None,
        notification_type=notification_type,
        api_key_id=sample_api_key.id,
        key_type=sample_api_key.key_type,
        job_id=sample_job.id,
        recipient_identifier=recipient_identifier
    )

    assert RecipientIdentifier.query.count() == 1
    assert RecipientIdentifier.query.get((notification.id, id_type, id_value)) \
        .notification_id == notification.id
    assert RecipientIdentifier.query.get((notification.id, id_type, id_value)) \
        .id_type == id_type
    assert RecipientIdentifier.query.get((notification.id, id_type, id_value)) \
        .id_value == id_value

    assert notification.recipient_identifiers[id_type].id_value == id_value
    assert notification.recipient_identifiers[id_type].id_type == id_type


@pytest.mark.parametrize('recipient_identifiers_enabled, recipient_identifier', [
    (True, None),
    (False, {'id_type': IdentifierType.VA_PROFILE_ID.value, 'id_value': 'foo'}),
    (False, None)
])
def test_persist_notification_should_not_persist_recipient_identifier_if_none_present_or_toggle_off(
        notify_db,
        recipient_identifiers_enabled,
        recipient_identifier,
        sample_job,
        sample_api_key,
        mocker
):
    mocker.patch(
        'app.notifications.process_notifications.accept_recipient_identifiers_enabled',
        return_value=recipient_identifiers_enabled
    )

    notification = persist_notification(
        template_id=sample_job.template.id,
        template_version=sample_job.template.version,
        service=sample_job.service,
        personalisation=None,
        notification_type='email',
        api_key_id=sample_api_key.id,
        key_type=sample_api_key.key_type,
        job_id=sample_job.id,
        recipient_identifier=recipient_identifier
    )

    assert RecipientIdentifier.query.count() == 0
    assert notification.recipient_identifiers == {}


@pytest.mark.parametrize('id_type, notification_type, expected_tasks', [
    (
        IdentifierType.VA_PROFILE_ID.value,
        EMAIL_TYPE,
        [
            send_va_onsite_notification_task,
            lookup_contact_info,
            lookup_recipient_communication_permissions,
            deliver_email
        ]
    ),
    (
        IdentifierType.VA_PROFILE_ID.value,
        SMS_TYPE,
        [
            send_va_onsite_notification_task,
            lookup_contact_info,
            lookup_recipient_communication_permissions,
            deliver_sms
        ]
    ),
    (
        IdentifierType.ICN.value,
        EMAIL_TYPE,
        [
            lookup_va_profile_id,
            send_va_onsite_notification_task,
            lookup_contact_info,
            lookup_recipient_communication_permissions,
            deliver_email
        ]
    ),
    (
        IdentifierType.ICN.value,
        SMS_TYPE,
        [
            lookup_va_profile_id,
            send_va_onsite_notification_task,
            lookup_contact_info,
            lookup_recipient_communication_permissions,
            deliver_sms
        ]
    ),
])
def test_send_notification_to_correct_queue_to_lookup_contact_info(
        client,
        mocker,
        notification_type,
        id_type,
        expected_tasks,
        sample_email_template,
        sample_sms_template_with_html
):
    mocker.patch(
        'app.notifications.process_notifications.is_feature_enabled',
        return_value=True
    )

    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')

    template = sample_email_template if notification_type == 'email' else sample_sms_template_with_html

    notification_id = str(uuid.uuid4())

    notification = Notification(
        id=notification_id,
        notification_type=notification_type,
        template=template
    )

    mock_template_id = uuid.uuid4()

    send_to_queue_for_recipient_info_based_on_recipient_identifier(
        notification, id_type, 'some_id_value', mock_template_id
    )

    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, expected_tasks):
        assert called_task.name == expected_task.name


def test_send_notification_with_sms_sender_rate_limit_uses_rate_limit_delivery_task(
        client,
        mocker
):
    mock_feature_flag(mocker, FeatureFlag.SMS_SENDER_RATE_LIMIT_ENABLED, 'True')
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')

    MockService = namedtuple('Service', ['id'])
    service = MockService(id='some service id')

    MockSmsSender = namedtuple('ServiceSmsSender', ['service_id', 'sms_sender', 'rate_limit'])
    sms_sender = MockSmsSender(service_id=service.id, sms_sender='+18888888888', rate_limit=2)

    MockTemplate = namedtuple('MockTemplate', ['communication_item_id'])
    template = MockTemplate(communication_item_id=1)

    mocker.patch(
        'app.notifications.process_notifications.dao_get_sms_sender_by_service_id_and_number',
        return_value=sms_sender
    )

    notification = Notification(
        id=str(uuid.uuid4()),
        notification_type='sms',
        reply_to_text=sms_sender.sms_sender,
        service_id=service.id,
        template=template
    )

    send_notification_to_queue(notification, False)

    assert mocked_chain.call_args[0][0].task == 'deliver_sms_with_rate_limiting'


def test_send_notification_without_sms_sender_rate_limit_uses_regular_delivery_task(
        client,
        mocker
):
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')
    deliver_sms_with_rate_limiting = mocker.patch(
        'app.celery.provider_tasks.deliver_sms_with_rate_limiting.apply_async'
    )

    MockService = namedtuple('Service', ['id'])
    service = MockService(id='some service id')

    MockTemplate = namedtuple('MockTemplate', ['communication_item_id'])
    template = MockTemplate(communication_item_id=1)

    MockSmsSender = namedtuple('ServiceSmsSender', ['service_id', 'sms_sender', 'rate_limit'])
    sms_sender = MockSmsSender(service_id=service.id, sms_sender='+18888888888', rate_limit=None)

    mocker.patch(
        'app.notifications.process_notifications.dao_get_sms_sender_by_service_id_and_number',
        return_value=sms_sender
    )

    notification = Notification(
        id=str(uuid.uuid4()),
        notification_type='sms',
        reply_to_text=sms_sender.sms_sender,
        service_id=service.id,
        template=template
    )

    send_notification_to_queue(notification, False)

    assert mocked_chain.call_args[0][0].task == 'deliver_sms'
    deliver_sms_with_rate_limiting.assert_not_called()
