import json
import pytest
from datetime import datetime
from freezegun import freeze_time
from uuid import uuid4

from app.celery import process_ses_receipts_tasks
from app.celery.research_mode_tasks import (
    ses_hard_bounce_callback,
    ses_notification_callback,
    ses_soft_bounce_callback,
)
from app.celery.service_callback_tasks import create_delivery_status_callback_data
from app.constants import (
    EMAIL_TYPE,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_TEMPORARY_FAILURE,
    STATUS_REASON_RETRYABLE,
    STATUS_REASON_UNDELIVERABLE,
    STATUS_REASON_UNREACHABLE,
)
from app.dao.notifications_dao import get_notification_by_id
from app.models import Complaint, Notification, NotificationHistory, Service, Template
from app.model import User
from app.notifications.notifications_ses_callback import (
    remove_emails_from_bounce,
    remove_emails_from_complaint,
)
from tests.app.db import (
    create_service_callback_api,
    ses_complaint_callback,
)


def ses_notification_complaint_callback(reference):
    """Sample callback data for an SES complaint event"""
    ses_message_body = {
        'complaint': {
            'arrivalDate': str(datetime.utcnow()),
            'complaintSubType': None,
            'feedbackId': reference,
            'timestamp': str(datetime.utcnow()),
            'complainedRecipients': [{'emailAddress': 'richard@example.com'}],
        },
        'eventType': 'Complaint',
        'mail': {
            'headersTruncated': False,
            'messageId': reference,
            'sendingAccountId': '171875617347',
            'source': '"U.S. Department of Veterans Affairs" <do-not-reply@notifications.va.gov>',
            'sourceArn': 'arn:aws-us-gov:ses:us-gov-west-1:171875617347:identity/notifications.va.gov',
            'destination': ['richard@example.com'],
            'tags': {
                'ses:caller-identity': ['project-dev-notification-api-task-role'],
                'ses:configuration-set': ['dev-configuration-set'],
                'ses:from-domain': ['dev-notifications.va.gov'],
                'ses:operation': ['SendRawEmail'],
                'ses:source-ip': ['152.129.43.2'],
                'ses:source-tls-version': ['TLSv1.3'],
            },
            'timestamp': str(datetime.utcnow()),
        },
    }

    return {'Message': json.dumps(ses_message_body)}


def test_process_ses_results(notify_db_session, sample_template, sample_notification, mocker):
    template = sample_template(template_type=EMAIL_TYPE)
    ref = str(uuid4())

    mock_send_email_status = mocker.patch(
        'app.celery.send_va_profile_notification_status_tasks.send_notification_status_to_va_profile.apply_async'
    )
    mock_send_email_status.return_value = None

    notification = sample_notification(
        template=template,
        reference=ref,
        sent_at=datetime.utcnow(),
        status=NOTIFICATION_SENDING,
        status_reason='just because',
    )
    assert notification.status == NOTIFICATION_SENDING
    assert notification.status_reason == 'just because'

    assert process_ses_receipts_tasks.process_ses_results(response=ses_notification_callback(reference=ref))

    notify_db_session.session.refresh(notification)
    assert notification.status == NOTIFICATION_DELIVERED
    assert notification.status_reason is None


def test_process_ses_results_notification_complaint(notify_db_session, sample_template, sample_notification, mocker):
    """Test that SES complaint referencing a notification is processed without error."""
    send_complaint_to_vanotify = mocker.patch(
        'app.celery.service_callback_tasks.send_complaint_to_vanotify.apply_async'
    )
    send_complaint_to_vanotify.return_value = None

    template = sample_template(template_type=EMAIL_TYPE)
    notification: Notification = sample_notification(
        status=NOTIFICATION_DELIVERED,
        template=template,
    )

    assert process_ses_receipts_tasks.process_ses_results(
        response=ses_notification_complaint_callback(reference=notification.reference)
    )
    send_complaint_to_vanotify.assert_called()


def test_process_ses_results_notification_history_complaint(
    notify_db_session, sample_template, sample_notification_history, mocker
):
    """Test that SES complaint referencing a notification in NotificationHistory is processed without error.

    NotificationHistory does not contain template so additional lookup is required during processing.
    """
    send_complaint_to_vanotify = mocker.patch(
        'app.celery.service_callback_tasks.send_complaint_to_vanotify.apply_async'
    )
    send_complaint_to_vanotify.return_value = None

    template = sample_template(template_type=EMAIL_TYPE)
    notification: NotificationHistory = sample_notification_history(
        status=NOTIFICATION_DELIVERED,
        template=template,
    )

    assert process_ses_receipts_tasks.process_ses_results(
        response=ses_notification_complaint_callback(reference=notification.reference)
    )
    send_complaint_to_vanotify.assert_called()


def test_process_ses_results_retry_called(mocker, sample_template, sample_notification):
    template = sample_template(template_type=EMAIL_TYPE)
    ref = str(uuid4())
    sample_notification(template=template, reference=ref, sent_at=datetime.utcnow(), status=NOTIFICATION_SENDING)

    mocker.patch('app.dao.notifications_dao._update_notification_status', side_effect=Exception('EXPECTED'))
    mocked = mocker.patch('app.celery.process_ses_receipts_tasks.process_ses_results.retry')
    process_ses_receipts_tasks.process_ses_results(response=ses_notification_callback(reference=ref))
    assert mocked.call_count != 0


def test_process_ses_results_call_to_publish_complaint(mocker, notify_api):
    publish_complaint = mocker.patch('app.celery.process_ses_receipts_tasks.publish_complaint')
    provider_message = ses_complaint_callback()

    complaint, notification, email = get_complaint_notification_and_email(mocker)

    mocker.patch(
        'app.celery.process_ses_receipts_tasks.handle_ses_complaint', return_value=(complaint, notification, email)
    )

    process_ses_receipts_tasks.process_ses_results(response=provider_message)

    publish_complaint.assert_called_once_with(complaint, notification, email)


def test_remove_emails_from_complaint():
    test_json = json.loads(ses_complaint_callback()['Message'])
    remove_emails_from_complaint(test_json)
    assert 'recipient1@example.com' not in json.dumps(test_json)


def test_remove_email_from_bounce():
    test_json = json.loads(ses_hard_bounce_callback(reference='ref1')['Message'])
    remove_emails_from_bounce(test_json)
    assert 'bounce@simulator.amazonses.com' not in json.dumps(test_json)


def test_ses_callback_should_call_send_delivery_status_to_service(
    notify_db_session, mocker, client, sample_template, sample_notification
):
    send_mock = mocker.patch('app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async')
    mock_send_email_status = mocker.patch(
        'app.celery.send_va_profile_notification_status_tasks.send_notification_status_to_va_profile.apply_async'
    )
    mock_send_email_status.return_value = None

    template = sample_template(template_type=EMAIL_TYPE)
    ref = str(uuid4())
    notification = sample_notification(template=template, status=NOTIFICATION_SENDING, reference=ref)

    service_callback = create_service_callback_api(service=template.service, url='https://original_url.com')

    process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference=ref))

    updated_notification = notify_db_session.session.get(Notification, notification.id)

    encrypted_data = create_delivery_status_callback_data(updated_notification, service_callback)
    send_mock.assert_called_once_with(
        args=(),
        kwargs={
            'service_callback_id': service_callback.id,
            'notification_id': str(notification.id),
            'encrypted_status_update': encrypted_data,
        },
        queue='service-callbacks',
    )


def test_wt_ses_callback_should_log_total_time(
    mocker,
    client,
    sample_template,
    sample_notification,
):
    template = sample_template(template_type=EMAIL_TYPE)
    with freeze_time('2001-01-01T12:00:00'):
        mock_log_total_time = mocker.patch('app.celery.common.log_notification_total_time')
        mocker.patch('app.celery.service_callback_tasks.check_and_queue_callback_task')
        mock_send_email_status = mocker.patch(
            'app.celery.send_va_profile_notification_status_tasks.send_notification_status_to_va_profile.apply_async'
        )
        mock_send_email_status.return_value = None

        ref = str(uuid4())

        notification = sample_notification(template=template, status=NOTIFICATION_SENDING, reference=ref)
        # Mock db call
        mocker.patch(
            'app.dao.notifications_dao.dao_get_notification_by_reference',
            return_value=notification,
        )
        process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference=ref))

        assert mock_log_total_time.called_once_with(
            notification.id,
            notification.created_at,
            NOTIFICATION_DELIVERED,
            'ses',
        )


def test_it_ses_callback_should_send_email_status_to_va_profile_when_set_to_delivered(
    mocker,
    client,
    sample_template,
    sample_notification,
):
    template = sample_template(template_type=EMAIL_TYPE)
    with freeze_time('2001-01-01T12:00:00'):
        mock_log_total_time = mocker.patch('app.celery.common.log_notification_total_time')
        mocker.patch('app.celery.process_ses_receipts_tasks.check_and_queue_callback_task')
        mocker.patch('app.celery.send_va_profile_notification_status_tasks.is_feature_enabled', return_value=True)
        mock_send_email_status = mocker.patch(
            'app.celery.send_va_profile_notification_status_tasks.send_notification_status_to_va_profile.apply_async'
        )
        ref = str(uuid4())

        # notification = sample_notification(template=template, status=NOTIFICATION_DELIVERED, reference=ref)  # no pass?
        notification = sample_notification(template=template, status=NOTIFICATION_SENDING, reference=ref)  # passes
        # Mock db call
        mocker.patch(
            'app.dao.notifications_dao.dao_get_notification_by_reference',
            return_value=notification,
        )
        process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference=ref))

        assert mock_log_total_time.called_once_with(
            notification.id,
            notification.created_at,
            NOTIFICATION_DELIVERED,
            'ses',
        )

        mock_send_email_status.assert_called_once()


def test_it_ses_callback_should_send_email_status_to_va_profile_with_notification_soft_bounce(
    mocker,
    client,
    sample_template,
    sample_notification,
):
    template = sample_template(template_type=EMAIL_TYPE)
    with freeze_time('2001-01-01T12:00:00'):
        mock_log_total_time = mocker.patch('app.celery.common.log_notification_total_time')
        mocker.patch('app.celery.process_ses_receipts_tasks.notifications_dao.dao_update_notification')
        mocker.patch('app.celery.process_ses_receipts_tasks.process_ses_results.retry')
        mocker.patch('app.celery.process_ses_receipts_tasks.check_and_queue_callback_task')
        mocker.patch('app.celery.send_va_profile_notification_status_tasks.is_feature_enabled', return_value=True)
        mock_send_email_status = mocker.patch(
            'app.celery.send_va_profile_notification_status_tasks.send_notification_status_to_va_profile.apply_async'
        )
        ref = str(uuid4())

        notification = sample_notification(template=template, status=NOTIFICATION_SENDING, reference=ref)
        # Mock db call
        mocker.patch(
            'app.dao.notifications_dao.dao_get_notification_by_reference',
            return_value=notification,
        )
        process_ses_receipts_tasks.process_ses_results(ses_soft_bounce_callback(reference=ref))

        assert get_notification_by_id(notification.id).status == NOTIFICATION_TEMPORARY_FAILURE

        mock_send_email_status.assert_called_once()

        assert mock_log_total_time.called_once_with(
            notification.id,
            notification.created_at,
            NOTIFICATION_DELIVERED,
            'ses',
        )


def test_it_ses_callback_should_send_email_status_to_va_profile_with_notification_hard_bounce(
    mocker,
    client,
    sample_template,
    sample_notification,
):
    # NOTIFICATION_PERMANENT_FAILURE
    template = sample_template(template_type=EMAIL_TYPE)
    with freeze_time('2001-01-01T12:00:00'):
        mock_log_total_time = mocker.patch('app.celery.common.log_notification_total_time')
        mocker.patch('app.celery.process_ses_receipts_tasks.notifications_dao.dao_update_notification')
        mock_callback = mocker.patch('app.celery.process_ses_receipts_tasks.check_and_queue_callback_task')
        mocker.patch('app.celery.send_va_profile_notification_status_tasks.is_feature_enabled', return_value=True)
        mock_send_email_status = mocker.patch(
            'app.celery.send_va_profile_notification_status_tasks.send_notification_status_to_va_profile.apply_async'
        )
        ref = str(uuid4())

        notification = sample_notification(template=template, status=NOTIFICATION_SENDING, reference=ref)
        # Mock db call
        mocker.patch(
            'app.dao.notifications_dao.dao_get_notification_by_reference',
            return_value=notification,
        )
        process_ses_receipts_tasks.process_ses_results(ses_hard_bounce_callback(reference=ref))

        assert get_notification_by_id(notification.id).status == NOTIFICATION_PERMANENT_FAILURE

        mock_callback.assert_called_once()

        mock_send_email_status.assert_called_once()

        assert mock_log_total_time.called_once_with(
            notification.id,
            notification.created_at,
            NOTIFICATION_DELIVERED,
            'ses',
        )


def test_ses_callback_should_not_update_notification_status_if_already_delivered(
    mocker, sample_template, sample_notification
):
    mock_dup = mocker.patch('app.celery.process_ses_receipts_tasks.notifications_dao.duplicate_update_warning')
    mock_upd = mocker.patch('app.celery.process_ses_receipts_tasks.notifications_dao._update_notification_status')

    template = sample_template(template_type=EMAIL_TYPE)
    ref = str(uuid4())
    notification = sample_notification(template=template, reference=ref, status=NOTIFICATION_DELIVERED)

    assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference=ref)) is None
    assert get_notification_by_id(notification.id).status == NOTIFICATION_DELIVERED

    mock_dup.assert_called_once()
    assert mock_dup.call_args.args[0].id == notification.id
    assert mock_dup.call_args.args[1] == NOTIFICATION_DELIVERED
    assert mock_upd.call_count == 0


def test_ses_callback_should_retry_if_notification_is_new(client, notify_db, mocker):
    mock_retry = mocker.patch('app.celery.process_ses_receipts_tasks.process_ses_results.retry')
    mock_logger = mocker.patch('app.celery.process_ses_receipts_tasks.current_app.logger.error')

    with freeze_time('2017-11-17T12:14:03.646Z'):
        assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference=str(uuid4()))) is None
        assert mock_logger.call_count == 0
        assert mock_retry.call_count == 1


def test_ses_callback_should_log_if_notification_is_missing(client, notify_db, mocker):
    mock_retry = mocker.patch('app.celery.process_ses_receipts_tasks.process_ses_results.retry')
    mock_logger = mocker.patch('app.celery.process_ses_receipts_tasks.current_app.logger.warning')

    with freeze_time('2017-11-17T12:34:03.646Z'):
        ref = str(uuid4())
        assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference=ref)) is None
        assert mock_retry.call_count == 0
        mock_logger.assert_called_once_with(
            'notification not found for reference: %s (update to %s)',
            ref,
            NOTIFICATION_DELIVERED,
        )


def test_ses_callback_should_not_retry_if_notification_is_old(client, notify_db, mocker):
    mock_retry = mocker.patch('app.celery.process_ses_receipts_tasks.process_ses_results.retry')
    mock_logger = mocker.patch('app.celery.process_ses_receipts_tasks.current_app.logger.error')

    with freeze_time('2017-11-21T12:14:03.646Z'):
        assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference=str(uuid4()))) is None
        assert mock_logger.call_count == 0
        assert mock_retry.call_count == 0


def test_ses_callback_does_not_call_send_delivery_status_if_no_db_entry(
    client,
    mocker,
    notify_db_session,
    sample_template,
    sample_notification,
):
    template = sample_template(template_type=EMAIL_TYPE)
    with freeze_time('2001-01-01T12:00:00'):
        ref = str(uuid4())
        send_mock = mocker.patch('app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async')
        mock_send_email_status = mocker.patch(
            'app.celery.send_va_profile_notification_status_tasks.send_notification_status_to_va_profile.apply_async'
        )
        mock_send_email_status.return_value = None
        notification_id = sample_notification(template=template, status=NOTIFICATION_SENDING, reference=ref).id

        assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference=ref))
        # The ORM does not update the notification object for some reason, so query it again (only affects tests)
        assert notify_db_session.session.get(Notification, notification_id).status == 'delivered'

        send_mock.assert_not_called()


def test_ses_callback_should_update_multiple_notification_status_sent(
    client,
    mocker,
    sample_template,
    sample_notification,
):
    send_mock = mocker.patch('app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async')

    mock_send_email_status = mocker.patch(
        'app.celery.send_va_profile_notification_status_tasks.send_notification_status_to_va_profile.apply_async'
    )
    mock_send_email_status.return_value = None

    template = sample_template(template_type=EMAIL_TYPE)
    sample_notification(
        template=template,
        status=NOTIFICATION_SENDING,
        reference='ref1',
    )
    sample_notification(
        template=template,
        status=NOTIFICATION_SENDING,
        reference='ref2',
    )
    sample_notification(
        template=template,
        status=NOTIFICATION_SENDING,
        reference='ref3',
    )
    create_service_callback_api(service=template.service, url='https://original_url.com')
    assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference='ref1'))
    assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference='ref2'))
    assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference='ref3'))
    assert send_mock.called


@pytest.mark.parametrize('status', [NOTIFICATION_DELIVERED, NOTIFICATION_SENDING, NOTIFICATION_SENT])
def test_ses_callback_should_set_status_to_temporary_failure(
    client,
    mocker,
    notify_db_session,
    sample_template,
    sample_notification,
    sample_service_callback,
    status,
):
    send_mock = mocker.patch('app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async')
    mock_send_email_status = mocker.patch(
        'app.celery.send_va_profile_notification_status_tasks.send_notification_status_to_va_profile.apply_async'
    )
    mock_send_email_status.return_value = None

    template = sample_template(template_type=EMAIL_TYPE)
    ref = str(uuid4())
    notification_id = sample_notification(
        template=template,
        status=status,
        reference=ref,
    ).id

    sample_service_callback(service=template.service, url='https://original_url.com')
    assert process_ses_receipts_tasks.process_ses_results(ses_soft_bounce_callback(reference=ref)) is None
    db_notification = notify_db_session.session.get(Notification, notification_id)
    assert db_notification.status == NOTIFICATION_TEMPORARY_FAILURE
    assert db_notification.status_reason == STATUS_REASON_RETRYABLE
    assert send_mock.called


@pytest.mark.parametrize('status', [NOTIFICATION_DELIVERED, NOTIFICATION_SENDING, NOTIFICATION_SENT])
def test_ses_callback_should_set_status_to_permanent_failure(
    client,
    mocker,
    notify_db_session,
    sample_template,
    sample_notification,
    sample_service_callback,
    status,
):
    send_mock = mocker.patch('app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async')
    mock_send_email_status = mocker.patch(
        'app.celery.send_va_profile_notification_status_tasks.send_notification_status_to_va_profile.apply_async'
    )
    mock_send_email_status.return_value = None

    template = sample_template(template_type=EMAIL_TYPE)
    ref = str(uuid4())
    notification_id = sample_notification(
        template=template,
        status=status,
        reference=ref,
    ).id
    sample_service_callback(service=template.service, url='https://original_url.com')

    assert process_ses_receipts_tasks.process_ses_results(ses_hard_bounce_callback(reference=ref)) is None
    db_notification = notify_db_session.session.get(Notification, notification_id)
    assert db_notification.status == NOTIFICATION_PERMANENT_FAILURE
    assert db_notification.status_reason == STATUS_REASON_UNREACHABLE
    assert send_mock.called


@pytest.mark.parametrize('bounce_status', [NOTIFICATION_TEMPORARY_FAILURE, NOTIFICATION_PERMANENT_FAILURE])
def test_ses_does_not_update_if_already_bounced(
    client,
    mocker,
    notify_db_session,
    sample_notification,
    sample_template,
    bounce_status,
):
    send_mock = mocker.patch('app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async')

    template = sample_template(template_type=EMAIL_TYPE)
    ref = str(uuid4())
    if bounce_status == NOTIFICATION_PERMANENT_FAILURE:
        # status_reason = 'Failed to deliver email due to hard bounce'
        status_reason = STATUS_REASON_UNDELIVERABLE
    elif bounce_status == NOTIFICATION_TEMPORARY_FAILURE:
        # status_reason = 'Temporarily failed to deliver email due to hard bounce'
        status_reason = STATUS_REASON_RETRYABLE
    else:
        raise NotImplementedError

    notification_id = sample_notification(
        template=template,
        status=bounce_status,
        status_reason=status_reason,
        reference=ref,
    ).id

    assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference=ref)) is None
    db_notification = notify_db_session.session.get(Notification, notification_id)
    assert db_notification.status == bounce_status
    assert db_notification.status_reason == status_reason
    assert not send_mock.called


def get_complaint_notification_and_email(mocker):
    service = mocker.Mock(Service, id='service_id', name='Service Name', users=[mocker.Mock(User, id='user_id')])
    template = mocker.Mock(
        Template, id='template_id', name='Email Template Name', service=service, template_type='email'
    )
    notification = mocker.Mock(
        Notification,
        service_id=template.service.id,
        service=template.service,
        template_id=template.id,
        template=template,
        status=NOTIFICATION_SENDING,
        reference='ref1',
    )
    complaint = mocker.Mock(
        Complaint,
        service_id=notification.service_id,
        notification_id=notification.id,
        feedback_id='feedback_id',
        complaint_type='complaint',
        complaint_date=datetime.utcnow(),
        created_at=datetime.now(),
    )
    recipient_email = 'recipient1@example.com'
    return complaint, notification, recipient_email


@pytest.mark.parametrize(
    'status, status_reason',
    (
        (NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNREACHABLE),
        (NOTIFICATION_TEMPORARY_FAILURE, STATUS_REASON_RETRYABLE),
    ),
)
def test_process_ses_results_no_bounce_regression(
    notify_db_session,
    sample_template,
    sample_notification,
    status,
    status_reason,
):
    """
    If a bounce status has been persisted for a notificaiton, no further status updates should occur.
    Soft bounces are temporary failures.  Hard bounces are permanent failures.
    """

    notification = sample_notification(
        template=sample_template(template_type=EMAIL_TYPE),
        status=status,
        status_reason=status_reason,
        reference=str(uuid4()),
    )

    # Simulate a delivery callback arriving after the message already bounced.
    response = ses_notification_callback(notification.reference)
    assert json.loads(response['Message'])['eventType'] == 'Delivery'
    assert process_ses_receipts_tasks.process_ses_results(response) is None

    notify_db_session.session.refresh(notification)
    assert notification.status == status, 'The status should not have changed.'
    assert notification.status_reason == status_reason


def test_process_ses_results_personalisation(notify_db_session, sample_template, sample_notification, mocker):
    template = sample_template(template_type=EMAIL_TYPE, content='Hello ((name))')
    ref = str(uuid4())

    mock_send_email_status = mocker.patch(
        'app.celery.send_va_profile_notification_status_tasks.send_notification_status_to_va_profile.apply_async'
    )
    mock_send_email_status.return_value = None

    notification = sample_notification(
        template=template,
        reference=ref,
        sent_at=datetime.utcnow(),
        status=NOTIFICATION_SENDING,
        status_reason='just because',
        personalisation={'name': 'Jo'},
    )
    assert process_ses_receipts_tasks.process_ses_results(response=ses_notification_callback(reference=ref))

    notify_db_session.session.refresh(notification)
    assert notification.status == NOTIFICATION_DELIVERED
    assert notification.personalisation == {'name': '<redacted>'}
