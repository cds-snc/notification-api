import datetime
import uuid
from collections import namedtuple

import pytest
from boto3.exceptions import Boto3Error
from freezegun import freeze_time
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from app.celery.contact_information_tasks import lookup_contact_info
from app.celery.lookup_recipient_communication_permissions_task import lookup_recipient_communication_permissions
from app.celery.lookup_va_profile_id_task import lookup_va_profile_id
from app.celery.onsite_notification_tasks import send_va_onsite_notification_task
from app.celery.provider_tasks import deliver_email, deliver_sms
from app.feature_flags import FeatureFlag
from app.models import (
    EMAIL_TYPE,
    KEY_TYPE_TEST,
    LETTER_TYPE,
    NOTIFICATION_CREATED,
    Notification,
    RecipientIdentifier,
    ScheduledNotification,
    SMS_TYPE,
    Template,
)
from app.notifications.process_notifications import (
    create_content_for_notification,
    persist_notification,
    persist_scheduled_notification,
    send_notification_to_queue,
    send_to_queue_for_recipient_info_based_on_recipient_identifier,
    simulated_recipient,
)
from app.va.identifier import IdentifierType
from app.v2.errors import BadRequestError
from notifications_utils.recipients import validate_and_format_email_address, validate_and_format_phone_number

from tests.app.factories.feature_flag import mock_feature_flag


def test_create_content_for_notification_passes(notify_db_session, sample_template, mocker):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    template = sample_template(template_type=EMAIL_TYPE)
    db_template = notify_db_session.session.get(Template, template.id)

    content = create_content_for_notification(db_template, None)
    assert str(content) == template.content


def test_create_content_for_notification_with_placeholders_passes(notify_db_session, sample_template, mocker):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    template = sample_template(content='Hello ((name))')
    db_template = notify_db_session.session.get(Template, template.id)

    content = create_content_for_notification(db_template, {'name': 'Bobby'})
    assert content.content == template.content
    assert 'Bobby' in str(content)


def test_create_content_for_notification_fails_with_missing_personalisation(notify_db_session, sample_template, mocker):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    template = sample_template(content='Hello ((name))\n((Additional placeholder))')
    db_template = notify_db_session.session.get(Template, template.id)

    with pytest.raises(BadRequestError):
        create_content_for_notification(db_template, None)


def test_create_content_for_notification_allows_additional_personalisation(notify_db_session, sample_template, mocker):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    template = sample_template(content='Hello ((name))\n((Additional placeholder))')
    db_template = notify_db_session.session.get(Template, template.id)

    create_content_for_notification(db_template, {'name': 'Bobby', 'Additional placeholder': 'Data'})


@pytest.mark.serial
@freeze_time('2016-01-01 11:09:00.061258')
def test_persist_notification_creates_and_save_to_db(
    notify_db_session,
    sample_api_key,
    sample_template,
    mocker,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    mocked_redis = mocker.patch('app.notifications.process_notifications.redis_store.get')

    template = sample_template()
    api_key = sample_api_key(template.service)

    data = {
        'template_id': template.id,
        'notification_id': uuid.uuid4(),
        'created_at': datetime.datetime.utcnow(),
        'reference': str(uuid.uuid4()),
        'billing_code': str(uuid.uuid4()),
        'recipient': '+16502532222',
        'notification_type': SMS_TYPE,
        'api_key_id': api_key.id,
        'key_type': api_key.key_type,
        'reply_to_text': template.service.get_default_sms_sender(),
        'service_id': template.service.id,
        'template_version': template.version,
        'personalisation': {},
    }

    # Intermittently makes the status 'technical-failure'
    # Cleaned by the template cleanup
    persist_notification(**data)

    db_notification = notify_db_session.session.get(Notification, data['notification_id'])

    assert db_notification.id == data['notification_id']
    assert db_notification.template_id == data['template_id']
    assert db_notification.template_version == data['template_version']
    assert db_notification.api_key_id == data['api_key_id']
    assert db_notification.key_type == data['key_type']
    assert db_notification.notification_type == data['notification_type']
    assert db_notification.created_at == data['created_at']
    assert db_notification.reference == data['reference']
    assert db_notification.reply_to_text == data['reply_to_text']
    assert db_notification.billing_code == data['billing_code']
    assert db_notification.status == NOTIFICATION_CREATED
    assert db_notification.billable_units == 0
    assert db_notification.updated_at is None
    assert db_notification.created_by_id is None
    assert db_notification.client_reference is None
    assert not db_notification.sent_at

    mocked_redis.assert_called_once_with(str(template.service_id) + '-2016-01-01-count')


def test_persist_notification_throws_exception_when_missing_template(sample_api_key, mocker):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    api_key = sample_api_key()
    notification = None

    with pytest.raises(SQLAlchemyError):
        notification = persist_notification(
            template_id=None,
            template_version=None,
            recipient='+16502532222',
            service_id=api_key.service.id,
            personalisation=None,
            notification_type=SMS_TYPE,
            api_key_id=api_key.id,
            key_type=api_key.key_type,
        )

    assert notification is None


def test_cache_is_not_incremented_on_failure_to_persist_notification(
    sample_api_key,
    mocker,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    api_key = sample_api_key()
    mocked_redis = mocker.patch('app.redis_store.get')
    mock_service_template_cache = mocker.patch('app.redis_store.get_all_from_hash')
    with pytest.raises(SQLAlchemyError):
        persist_notification(
            template_id=None,
            template_version=None,
            recipient='+16502532222',
            service_id=api_key.service.id,
            personalisation=None,
            notification_type=SMS_TYPE,
            api_key_id=api_key.id,
            key_type=api_key.key_type,
        )
    mocked_redis.assert_not_called()
    mock_service_template_cache.assert_not_called()


def test_persist_notification_does_not_increment_cache_if_test_key(
    notify_db_session,
    sample_api_key,
    sample_template,
    mocker,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    template = sample_template()
    api_key = sample_api_key(service=template.service, key_type=KEY_TYPE_TEST)

    mocker.patch('app.notifications.process_notifications.redis_store.get', return_value='cache')
    mocker.patch('app.notifications.process_notifications.redis_store.get_all_from_hash', return_value='cache')
    daily_limit_cache = mocker.patch('app.notifications.process_notifications.redis_store.incr')
    template_usage_cache = mocker.patch('app.notifications.process_notifications.redis_store.increment_hash_value')

    notification_id = uuid.uuid4()

    # Cleaned by the template cleanup
    persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient='+16502532222',
        service_id=template.service.id,
        personalisation={},
        notification_type=SMS_TYPE,
        api_key_id=api_key.id,
        key_type=api_key.key_type,
        reference=str(uuid.uuid4()),
        notification_id=notification_id,
    )

    assert notify_db_session.session.get(Notification, notification_id)
    assert not daily_limit_cache.called
    assert not template_usage_cache.called


@freeze_time('2016-01-01 11:09:00.061258')
def test_persist_notification_with_optionals(
    notify_db_session,
    sample_api_key,
    sample_template,
    mocker,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    api_key = sample_api_key()
    template = sample_template(service=api_key.service)
    service = api_key.service
    mocked_redis = mocker.patch('app.notifications.process_notifications.redis_store.get')
    notification_id = uuid.uuid4()
    created_at = datetime.datetime(2016, 11, 11, 16, 8, 18)

    # Cleaned by the template cleanup
    persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient='+16502532222',
        service_id=service.id,
        personalisation=None,
        notification_type=SMS_TYPE,
        api_key_id=api_key.id,
        key_type=api_key.key_type,
        created_at=created_at,
        client_reference='ref from client',
        notification_id=notification_id,
        created_by_id=api_key.created_by_id,
    )

    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    assert persisted_notification.id == notification_id
    assert persisted_notification.created_at == created_at
    mocked_redis.assert_called_once_with(str(service.id) + '-2016-01-01-count')
    assert persisted_notification.client_reference == 'ref from client'
    assert persisted_notification.reference is None
    assert persisted_notification.international is False
    assert persisted_notification.phone_prefix == '1'
    assert persisted_notification.rate_multiplier == 1
    assert persisted_notification.created_by_id == api_key.created_by_id
    assert not persisted_notification.reply_to_text


@freeze_time('2016-01-01 11:09:00.061258')
def test_persist_notification_doesnt_touch_cache_for_old_keys_that_dont_exist(
    sample_api_key,
    sample_template,
    mocker,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    api_key = sample_api_key()
    template = sample_template(service=api_key.service)
    mock_incr = mocker.patch('app.notifications.process_notifications.redis_store.incr')
    mocker.patch('app.notifications.process_notifications.redis_store.get', return_value=None)
    mocker.patch('app.notifications.process_notifications.redis_store.get_all_from_hash', return_value=None)

    # Cleaned by the template cleanup
    persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient='+16502532222',
        service_id=api_key.service.id,
        personalisation={},
        notification_type=SMS_TYPE,
        api_key_id=api_key.id,
        key_type=api_key.key_type,
        reference='ref',
    )

    mock_incr.assert_not_called()


@freeze_time('2016-01-01 11:09:00.061258')
def test_persist_notification_increments_cache_if_key_exists(
    sample_api_key,
    sample_template,
    mocker,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    api_key = sample_api_key()
    template = sample_template(service=api_key.service)
    service = template.service
    mock_incr = mocker.patch('app.notifications.process_notifications.redis_store.incr')
    mocker.patch('app.notifications.process_notifications.redis_store.get', return_value=1)
    mocker.patch('app.notifications.process_notifications.redis_store.get_all_from_hash', return_value={template.id, 1})

    # Cleaned by the template cleanup
    persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient='+16502532222',
        service_id=service.id,
        personalisation={},
        notification_type=SMS_TYPE,
        api_key_id=api_key.id,
        key_type=api_key.key_type,
        reference='ref2',
    )

    mock_incr.assert_called_once_with(str(service.id) + '-2016-01-01-count')


@pytest.mark.parametrize(
    'research_mode, requested_queue, notification_type, key_type, expected_queue, expected_tasks',
    [
        (True, None, SMS_TYPE, 'normal', 'research-mode-tasks', [deliver_sms]),
        (True, None, EMAIL_TYPE, 'normal', 'research-mode-tasks', [deliver_email]),
        (True, None, EMAIL_TYPE, 'team', 'research-mode-tasks', [deliver_email]),
        (False, None, SMS_TYPE, 'normal', 'send-sms-tasks', [deliver_sms]),
        (False, None, EMAIL_TYPE, 'normal', 'send-email-tasks', [deliver_email]),
        (False, None, SMS_TYPE, 'team', 'send-sms-tasks', [deliver_sms]),
        (False, None, SMS_TYPE, 'test', 'research-mode-tasks', [deliver_sms]),
        (True, 'notify-internal-tasks', EMAIL_TYPE, 'normal', 'research-mode-tasks', [deliver_email]),
        (False, 'notify-internal-tasks', SMS_TYPE, 'normal', 'notify-internal-tasks', [deliver_sms]),
        (False, 'notify-internal-tasks', EMAIL_TYPE, 'normal', 'notify-internal-tasks', [deliver_email]),
        (False, 'notify-internal-tasks', SMS_TYPE, 'test', 'research-mode-tasks', [deliver_sms]),
    ],
)
def test_send_notification_to_queue_with_no_recipient_identifiers(
    research_mode,
    requested_queue,
    notification_type,
    key_type,
    expected_queue,
    expected_tasks,
    mocker,
    sample_template,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')
    template = sample_template(template_type=notification_type)
    MockService = namedtuple('Service', ['id'])
    service = MockService(id=uuid.uuid4())

    MockSmsSender = namedtuple('ServiceSmsSender', ['service_id', 'sms_sender', 'rate_limit'])
    sms_sender = MockSmsSender(service_id=service.id, sms_sender='+18888888888', rate_limit=1)

    NotificationTuple = namedtuple(
        'Notification', ['id', 'key_type', 'notification_type', 'created_at', 'template', 'service_id', 'reply_to_text']
    )

    mocker.patch(
        'app.notifications.process_notifications.dao_get_service_sms_sender_by_service_id_and_number', return_value=None
    )

    MockSmsSender = namedtuple('ServiceSmsSender', ['service_id', 'sms_sender', 'rate_limit'])
    sms_sender = MockSmsSender(service_id=service.id, sms_sender='+18888888888', rate_limit=None)

    notification = NotificationTuple(
        id=uuid.uuid4(),
        key_type=key_type,
        notification_type=notification_type,
        created_at=datetime.datetime(2016, 11, 11, 16, 8, 18),
        template=template,
        service_id=service.id,
        reply_to_text=sms_sender.sms_sender,
    )

    send_notification_to_queue(notification=notification, research_mode=research_mode, queue=requested_queue)

    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, expected_tasks):
        assert called_task.name == expected_task.name
        called_task_notification_arg = args[0].args[0]
        assert called_task_notification_arg == str(notification.id)


@pytest.mark.parametrize(
    'research_mode, requested_queue, notification_type, key_type, expected_queue, '
    'request_recipient_id_type, request_recipient_id_value, expected_tasks',
    [
        (
            True,
            None,
            SMS_TYPE,
            'normal',
            'research-mode-tasks',
            IdentifierType.VA_PROFILE_ID.value,
            'some va profile id',
            [lookup_recipient_communication_permissions, deliver_sms],
        ),
        (
            True,
            None,
            EMAIL_TYPE,
            'normal',
            'research-mode-tasks',
            IdentifierType.PID.value,
            'some pid',
            [lookup_va_profile_id, lookup_recipient_communication_permissions, deliver_email],
        ),
        (
            True,
            None,
            EMAIL_TYPE,
            'team',
            'research-mode-tasks',
            IdentifierType.ICN.value,
            'some icn',
            [lookup_va_profile_id, lookup_recipient_communication_permissions, deliver_email],
        ),
        (
            True,
            'notify-internal-tasks',
            EMAIL_TYPE,
            'normal',
            'research-mode-tasks',
            IdentifierType.VA_PROFILE_ID.value,
            'some va profile id',
            [lookup_recipient_communication_permissions, deliver_email],
        ),
        (
            False,
            None,
            SMS_TYPE,
            'normal',
            'send-sms-tasks',
            IdentifierType.PID.value,
            'some pid',
            [lookup_va_profile_id, lookup_recipient_communication_permissions, deliver_sms],
        ),
        (
            False,
            None,
            EMAIL_TYPE,
            'normal',
            'send-email-tasks',
            IdentifierType.ICN.value,
            'some icn',
            [lookup_va_profile_id, lookup_recipient_communication_permissions, deliver_email],
        ),
        (
            False,
            None,
            SMS_TYPE,
            'team',
            'send-sms-tasks',
            IdentifierType.VA_PROFILE_ID.value,
            'some va profile id',
            [lookup_recipient_communication_permissions, deliver_sms],
        ),
        (
            False,
            None,
            SMS_TYPE,
            'test',
            'research-mode-tasks',
            IdentifierType.PID.value,
            'some pid',
            [lookup_va_profile_id, lookup_recipient_communication_permissions, deliver_sms],
        ),
        (
            False,
            'notify-internal-tasks',
            SMS_TYPE,
            'normal',
            'notify-internal-tasks',
            IdentifierType.ICN.value,
            'some icn',
            [lookup_va_profile_id, lookup_recipient_communication_permissions, deliver_sms],
        ),
        (
            False,
            'notify-internal-tasks',
            EMAIL_TYPE,
            'normal',
            'notify-internal-tasks',
            IdentifierType.VA_PROFILE_ID.value,
            'some va profile id',
            [lookup_recipient_communication_permissions, deliver_email],
        ),
        (
            False,
            'notify-internal-tasks',
            SMS_TYPE,
            'test',
            'research-mode-tasks',
            IdentifierType.PID.value,
            'some pid',
            [lookup_va_profile_id, lookup_recipient_communication_permissions, deliver_sms],
        ),
    ],
)
def test_send_notification_to_queue_with_recipient_identifiers(
    research_mode,
    requested_queue,
    notification_type,
    key_type,
    expected_queue,
    request_recipient_id_type,
    request_recipient_id_value,
    expected_tasks,
    mocker,
    sample_communication_item,
    sample_template,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    mock_feature_flag(mocker, FeatureFlag.SMS_SENDER_RATE_LIMIT_ENABLED, 'True')
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')
    template = sample_template(
        template_type=notification_type,
        content='Hello (( Name))\nHere is <em>some HTML</em> & entities' if notification_type == SMS_TYPE else None,
    )
    template.service.prefix_sms = notification_type == SMS_TYPE  # True only for SMS_TYPE

    MockService = namedtuple('Service', ['id'])
    service = MockService(id=uuid.uuid4())
    MockSmsSender = namedtuple('ServiceSmsSender', ['service_id', 'sms_sender', 'rate_limit'])
    sms_sender = MockSmsSender(service_id=service.id, sms_sender='+18888888888', rate_limit=None)

    mocker.patch(
        'app.notifications.process_notifications.dao_get_service_sms_sender_by_service_id_and_number',
        return_value=sms_sender,
    )

    TestNotification = namedtuple(
        'Notification',
        [
            'id',
            'key_type',
            'notification_type',
            'created_at',
            'template',
            'recipient_identifiers',
            'service_id',
            'reply_to_text',
            'sms_sender',
        ],
    )
    notification_id = uuid.uuid4()
    notification = TestNotification(
        id=notification_id,
        key_type=key_type,
        notification_type=notification_type,
        created_at=datetime.datetime(2016, 11, 11, 16, 8, 18),
        template=template,
        recipient_identifiers={
            f'{request_recipient_id_type}': RecipientIdentifier(
                notification_id=notification_id, id_type=request_recipient_id_type, id_value=request_recipient_id_value
            )
        },
        service_id=service.id,
        reply_to_text=sms_sender.sms_sender,
        sms_sender=sms_sender,
    )

    send_notification_to_queue(
        notification=notification,
        research_mode=research_mode,
        queue=requested_queue,
        recipient_id_type=request_recipient_id_type,
    )

    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, expected_tasks):
        assert called_task.name == expected_task.name


def test_send_notification_to_queue_throws_exception_deletes_notification(
    sample_api_key,
    sample_notification,
    mocker,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    notification = sample_notification(api_key=sample_api_key())
    mock_feature_flag(mocker, FeatureFlag.SMS_SENDER_RATE_LIMIT_ENABLED, 'False')
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain', side_effect=Boto3Error('EXPECTED'))
    mocker.patch('app.notifications.process_notifications.dao_get_service_sms_sender_by_service_id_and_number')
    with pytest.raises(Boto3Error):
        send_notification_to_queue(notification, False)

    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, ['send-sms-tasks']):
        assert called_task.args[0] == str(notification.id)
        assert called_task.options['queue'] == expected_task


@pytest.mark.parametrize(
    'to_address, notification_type, expected',
    [
        ('+16132532222', 'sms', True),
        ('+16132532223', 'sms', True),
        ('6132532222', 'sms', True),
        ('simulate-delivered@notifications.va.gov', 'email', True),
        ('simulate-delivered-2@notifications.va.gov', 'email', True),
        ('simulate-delivered-3@notifications.va.gov', 'email', True),
        ('6132532225', 'sms', False),
        ('valid_email@test.com', 'email', False),
    ],
)
def test_simulated_recipient(to_address, notification_type, expected, mocker):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

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

    if notification_type == EMAIL_TYPE:
        formatted_address = validate_and_format_email_address(to_address)
    else:
        formatted_address = validate_and_format_phone_number(to_address)

    is_simulated_address = simulated_recipient(formatted_address, notification_type)

    assert is_simulated_address == expected


@pytest.mark.parametrize(
    'recipient, expected_international, expected_prefix, expected_units',
    [
        ('6502532222', False, '1', 1),  # NA
        ('+16502532222', False, '1', 1),  # NA
        ('+79587714230', True, '7', 1),  # Russia
        ('+360623400400', True, '36', 3),  # Hungary
    ],
)
def test_persist_notification_with_international_info_stores_correct_info(
    notify_db_session,
    sample_api_key,
    sample_template,
    mocker,
    recipient,
    expected_international,
    expected_prefix,
    expected_units,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    template = sample_template()
    api_key = sample_api_key(service=template.service)

    notification_id = uuid.uuid4()

    # Cleaned by the template cleanup
    persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient=recipient,
        service_id=template.service.id,
        personalisation=None,
        notification_type=SMS_TYPE,
        api_key_id=api_key.id,
        key_type=api_key.key_type,
        client_reference='ref from client',
        notification_id=notification_id,
    )

    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    assert persisted_notification.international is expected_international
    assert persisted_notification.phone_prefix == expected_prefix
    assert persisted_notification.rate_multiplier == expected_units


def test_persist_notification_with_international_info_does_not_store_for_email(
    notify_db_session,
    sample_api_key,
    sample_template,
    mocker,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    template = sample_template()
    api_key = sample_api_key(service=template.service)

    notification_id = uuid.uuid4()

    # Cleaned by the template cleanup
    persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient='foo@bar.com',
        service_id=api_key.service.id,
        personalisation=None,
        notification_type=EMAIL_TYPE,
        api_key_id=api_key.id,
        key_type=api_key.key_type,
        client_reference='ref from client',
        notification_id=notification_id,
    )

    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    assert persisted_notification.international is False
    assert persisted_notification.phone_prefix is None
    assert persisted_notification.rate_multiplier is None


# This test assumes the local timezone is EST
def test_persist_scheduled_notification(notify_db_session, sample_api_key, sample_notification, mocker):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    api_key = sample_api_key()
    notification = sample_notification(api_key=api_key)

    # Cleaned by the template cleanup
    persist_scheduled_notification(notification.id, '2017-05-12 14:15')
    stmt = select(ScheduledNotification).where(ScheduledNotification.notification_id == notification.id)
    scheduled_notification = notify_db_session.session.scalar(stmt)

    assert scheduled_notification.notification_id == notification.id
    assert scheduled_notification.scheduled_for == datetime.datetime(2017, 5, 12, 18, 15)


@pytest.mark.parametrize(
    'recipient, expected_recipient_normalised',
    [
        ('6502532222', '+16502532222'),
        ('  6502532223', '+16502532223'),
        ('6502532223', '+16502532223'),
    ],
)
def test_persist_sms_notification_stores_normalised_number(
    notify_db_session,
    sample_api_key,
    sample_template,
    mocker,
    recipient,
    expected_recipient_normalised,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    template = sample_template()
    api_key = sample_api_key(service=template.service)

    notification_id = uuid.uuid4()

    # Cleaned by the template cleanup
    persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient=recipient,
        service_id=api_key.service.id,
        personalisation=None,
        notification_type=SMS_TYPE,
        api_key_id=api_key.id,
        key_type=api_key.key_type,
        notification_id=notification_id,
    )

    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    assert persisted_notification.to == recipient
    assert persisted_notification.normalised_to == expected_recipient_normalised


@pytest.mark.parametrize(
    'recipient, expected_recipient_normalised', [('FOO@bar.com', 'foo@bar.com'), ('BAR@foo.com', 'bar@foo.com')]
)
def test_persist_email_notification_stores_normalised_email(
    notify_db_session,
    sample_api_key,
    sample_template,
    mocker,
    recipient,
    expected_recipient_normalised,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    template = sample_template()
    api_key = sample_api_key(service=template.service)

    notification_id = uuid.uuid4()

    # Cleaned by the template cleanup
    persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient=recipient,
        service_id=api_key.service.id,
        personalisation=None,
        notification_type=EMAIL_TYPE,
        api_key_id=api_key.id,
        key_type=api_key.key_type,
        notification_id=notification_id,
    )
    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    assert persisted_notification.to == recipient
    assert persisted_notification.normalised_to == expected_recipient_normalised


@pytest.mark.skip(reason='Mislabelled for route removal, fails when unskipped')
def test_persist_notification_with_billable_units_stores_correct_info(
    notify_db_session,
    mocker,
    sample_service,
    sample_template,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    service = sample_service(service_permissions=[LETTER_TYPE])
    template = sample_template(service=service, template_type=LETTER_TYPE)
    mocker.patch('app.dao.templates_dao.dao_get_template_by_id', return_value=template)

    # Cleaned by the template cleanup
    persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient='123 Main Street',
        service_id=template.service.id,
        personalisation=None,
        notification_type=template.template_type,
        api_key_id=None,
        key_type='normal',
        billable_units=3,
        template_postage=template.postage,
    )

    stmt = select(Notification)
    persisted_notification = notify_db_session.session.scalars(stmt).all()[0]

    assert persisted_notification.billable_units == 3


@pytest.mark.parametrize(
    'notification_type',
    [
        EMAIL_TYPE,
        SMS_TYPE,
    ],
)
@pytest.mark.parametrize(
    'id_type, id_value',
    [
        (IdentifierType.VA_PROFILE_ID.value, 'some va profile id'),
        (IdentifierType.PID.value, 'some pid'),
        (IdentifierType.ICN.value, 'some icn'),
    ],
)
def test_persist_notification_persists_recipient_identifiers(
    notify_db_session,
    notification_type,
    id_type,
    id_value,
    sample_api_key,
    sample_template,
    mocker,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    mocker.patch('app.notifications.process_notifications.accept_recipient_identifiers_enabled', return_value=True)
    template = sample_template(template_type=notification_type)
    api_key = sample_api_key()
    recipient_identifier = {'id_type': id_type, 'id_value': id_value}

    notification_id = uuid.uuid4()
    # Cleaned by the template cleanup
    persist_notification(
        template_id=template.id,
        template_version=template.version,
        service_id=api_key.service.id,
        personalisation=None,
        notification_type=notification_type,
        api_key_id=api_key.id,
        key_type=api_key.key_type,
        recipient_identifier=recipient_identifier,
        notification_id=notification_id,
    )

    recipient_identifier = notify_db_session.session.get(RecipientIdentifier, (notification_id, id_type, id_value))

    try:
        # Persisted correctly
        assert recipient_identifier.notification_id == notification_id
        assert recipient_identifier.id_type == id_type
        assert recipient_identifier.id_value == id_value
    finally:
        # Teardown
        stmt = delete(RecipientIdentifier).where(RecipientIdentifier.notification_id == notification_id)
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


@pytest.mark.parametrize(
    'recipient_identifiers_enabled, recipient_identifier',
    [(True, None), (False, {'id_type': IdentifierType.VA_PROFILE_ID.value, 'id_value': 'foo'}), (False, None)],
)
def test_persist_notification_should_not_persist_recipient_identifier_if_none_present_or_toggle_off(
    notify_db_session,
    recipient_identifiers_enabled,
    recipient_identifier,
    sample_api_key,
    sample_template,
    mocker,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    mocker.patch(
        'app.notifications.process_notifications.accept_recipient_identifiers_enabled',
        return_value=recipient_identifiers_enabled,
    )

    template = sample_template()
    api_key = sample_api_key(template.service)

    # Cleaned by the template cleanup
    notification = persist_notification(
        template_id=template.id,
        template_version=template.version,
        service_id=api_key.service.id,
        personalisation=None,
        notification_type=EMAIL_TYPE,
        api_key_id=api_key.id,
        key_type=api_key.key_type,
        recipient_identifier=recipient_identifier,
    )

    # Persisted correctly
    assert notification.recipient_identifiers == {}

    # DB stored correctly
    stmt = select(RecipientIdentifier).where(RecipientIdentifier.notification_id == notification.id)
    assert notify_db_session.session.scalar(stmt) is None


@pytest.mark.parametrize(
    'id_type, notification_type, expected_tasks',
    [
        (
            IdentifierType.VA_PROFILE_ID.value,
            EMAIL_TYPE,
            [
                send_va_onsite_notification_task,
                lookup_contact_info,
                deliver_email,
            ],
        ),
        (
            IdentifierType.VA_PROFILE_ID.value,
            SMS_TYPE,
            [
                send_va_onsite_notification_task,
                lookup_contact_info,
                deliver_sms,
            ],
        ),
        (
            IdentifierType.ICN.value,
            EMAIL_TYPE,
            [
                lookup_va_profile_id,
                send_va_onsite_notification_task,
                lookup_contact_info,
                deliver_email,
            ],
        ),
        (
            IdentifierType.ICN.value,
            SMS_TYPE,
            [
                lookup_va_profile_id,
                send_va_onsite_notification_task,
                lookup_contact_info,
                deliver_sms,
            ],
        ),
    ],
)
def test_send_notification_to_correct_queue_to_lookup_contact_info(
    client,
    mocker,
    notification_type,
    id_type,
    expected_tasks,
    sample_template,
):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    mock_feature_flag(mocker, FeatureFlag.SMS_SENDER_RATE_LIMIT_ENABLED, 'True')
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')

    template = sample_template(template_type=notification_type)
    notification_id = str(uuid.uuid4())
    notification = Notification(id=notification_id, notification_type=notification_type, template=template)
    mock_template_id = uuid.uuid4()

    send_to_queue_for_recipient_info_based_on_recipient_identifier(
        notification, id_type, 'some_id_value', mock_template_id
    )

    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, expected_tasks):
        assert called_task.name == expected_task.name


def test_send_notification_with_sms_sender_rate_limit_uses_rate_limit_delivery_task(client, mocker):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

    mock_feature_flag(mocker, FeatureFlag.SMS_SENDER_RATE_LIMIT_ENABLED, 'True')
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')

    MockService = namedtuple('Service', ['id'])
    service = MockService(id='some service id')

    MockSmsSender = namedtuple('ServiceSmsSender', ['service_id', 'sms_sender', 'rate_limit'])
    sms_sender = MockSmsSender(service_id=service.id, sms_sender='+18888888888', rate_limit=2)

    MockTemplate = namedtuple('MockTemplate', ['communication_item_id'])
    template = MockTemplate(communication_item_id=1)

    mocker.patch(
        'app.notifications.process_notifications.dao_get_service_sms_sender_by_service_id_and_number',
        return_value=sms_sender,
    )

    notification = Notification(
        id=str(uuid.uuid4()),
        notification_type=SMS_TYPE,
        reply_to_text=sms_sender.sms_sender,
        service_id=service.id,
        template=template,
    )

    send_notification_to_queue(notification, False)

    assert mocked_chain.call_args[0][0].task == 'deliver_sms_with_rate_limiting'


def test_send_notification_without_sms_sender_rate_limit_uses_regular_delivery_task(client, mocker):
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_COMBINE_CONTACT_INFO_AND_PERMISSIONS_LOOKUP, 'True')
    mock_feature_flag(mocker, FeatureFlag.VA_PROFILE_V3_IDENTIFY_MOBILE_TELEPHONE_NUMBERS, 'True')

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
        'app.notifications.process_notifications.dao_get_service_sms_sender_by_service_id_and_number',
        return_value=sms_sender,
    )

    notification = Notification(
        id=str(uuid.uuid4()),
        notification_type=SMS_TYPE,
        reply_to_text=sms_sender.sms_sender,
        service_id=service.id,
        template=template,
    )

    send_notification_to_queue(notification, False)

    assert mocked_chain.call_args[0][0].task == 'deliver_sms'
    deliver_sms_with_rate_limiting.assert_not_called()
