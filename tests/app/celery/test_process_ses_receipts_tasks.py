import json
import pytest
from datetime import datetime
from freezegun import freeze_time
from requests import ConnectTimeout, ReadTimeout
from sqlalchemy import select
import uuid
from uuid import uuid4

from app.celery import process_ses_receipts_tasks
from app.celery.exceptions import AutoRetryException
from app.celery.research_mode_tasks import ses_hard_bounce_callback, ses_soft_bounce_callback, ses_notification_callback
from app.celery.service_callback_tasks import create_delivery_status_callback_data
from app.dao.notifications_dao import get_notification_by_id
from app.models import (
    Complaint,
    EMAIL_TYPE,
    Notification,
    Service,
    Template,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_SENT,
    NOTIFICATION_SENDING,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
)
from app.model import User
from app.notifications.notifications_ses_callback import remove_emails_from_complaint, remove_emails_from_bounce

from tests.app.db import (
    ses_complaint_callback,
    ses_smtp_complaint_callback,
    create_service_callback_api,
    ses_smtp_notification_callback,
    ses_smtp_hard_bounce_callback,
    ses_smtp_soft_bounce_callback,
)


def test_process_ses_results(notify_db_session, sample_template, sample_notification):
    template = sample_template(template_type=EMAIL_TYPE)
    ref = str(uuid4())

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

    template = sample_template(template_type=EMAIL_TYPE)
    ref = str(uuid4())
    notification = sample_notification(template=template, status=NOTIFICATION_SENDING, reference=ref)

    service_callback = create_service_callback_api(service=template.service, url='https://original_url.com')

    process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference=ref))

    updated_notification = notify_db_session.session.get(Notification, notification.id)

    encrypted_data = create_delivery_status_callback_data(updated_notification, service_callback)
    send_mock.assert_called_once_with(
        [service_callback.id, str(notification.id), encrypted_data], queue='service-callbacks'
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


def test_it_ses_callback_should_not_send_email_status_to_va_profile_when_feature_flag_disabled(
    mocker,
    client,
    sample_template,
    sample_notification,
):
    template = sample_template(template_type=EMAIL_TYPE)
    with freeze_time('2001-01-01T12:00:00'):
        mock_log_total_time = mocker.patch('app.celery.common.log_notification_total_time')
        mocker.patch('app.celery.process_ses_receipts_tasks.check_and_queue_callback_task')
        mocker.patch('app.celery.process_ses_receipts_tasks.is_feature_enabled', return_value=False)
        mock_send_email_status = mocker.patch(
            'app.celery.process_ses_receipts_tasks.send_email_status_to_va_profile.apply_async'
        )
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

        mock_send_email_status.assert_not_called()


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
        mocker.patch('app.celery.process_ses_receipts_tasks.is_feature_enabled', return_value=True)
        mock_send_email_status = mocker.patch(
            'app.celery.process_ses_receipts_tasks.send_email_status_to_va_profile.apply_async'
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
        mocker.patch('app.celery.process_ses_receipts_tasks.is_feature_enabled', return_value=True)
        mock_send_email_status = mocker.patch(
            'app.celery.process_ses_receipts_tasks.send_email_status_to_va_profile.apply_async'
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
        mocker.patch('app.celery.process_ses_receipts_tasks.is_feature_enabled', return_value=True)
        mock_send_email_status = mocker.patch(
            'app.celery.process_ses_receipts_tasks.send_email_status_to_va_profile.apply_async'
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
    assert db_notification.status_reason == 'Temporarily failed to deliver email due to soft bounce'
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
    assert db_notification.status_reason == 'Failed to deliver email due to hard bounce'
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
        status_reason = 'Failed to deliver email due to hard bounce'
    elif bounce_status == NOTIFICATION_TEMPORARY_FAILURE:
        status_reason = 'Temporarily failed to deliver email due to hard bounce'
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


@pytest.mark.serial
def test_process_ses_smtp_results(
    sample_smtp_template,
    mocker,
):
    template = sample_smtp_template()
    mocker.patch.dict('app.celery.process_ses_receipts_tasks.current_app.config', {'SMTP_TEMPLATE_ID': template.id})
    # Trouble processing smtp user with multiple workers - dao_services_by_partial_smtp_name finds multiple rows
    assert process_ses_receipts_tasks.process_ses_smtp_results(response=ses_smtp_notification_callback())


@pytest.mark.serial
def test_process_ses_smtp_results_in_complaint(
    client,
    notify_db_session,
    sample_notification,
    mocker,
    sample_smtp_template,
):
    template = sample_smtp_template()
    sample_notification(template=template, reference=str(uuid4()))

    mocked = mocker.patch('app.dao.notifications_dao.update_notification_status_by_reference')
    mocker.patch.dict('app.celery.process_ses_receipts_tasks.current_app.config', {'SMTP_TEMPLATE_ID': template.id})

    # Generate id for multi-worker testing
    feedback_id = str(uuid4())
    # Trouble processing smtp user with multiple workers - dao_services_by_partial_smtp_name finds multiple rows
    process_ses_receipts_tasks.process_ses_smtp_results(response=ses_smtp_complaint_callback(feedback_id))
    assert mocked.call_count == 0

    stmt = select(Complaint).where(Complaint.feedback_id == feedback_id)
    complaints = notify_db_session.session.scalars(stmt).all()
    assert len(complaints) == 1


@pytest.mark.serial
def test_ses_smtp_callback_should_set_status_to_temporary_failure(
    client,
    sample_notification,
    sample_smtp_template,
    mocker,
):
    template = sample_smtp_template()
    send_mock = mocker.patch('app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async')
    mocker.patch.dict('app.celery.process_ses_receipts_tasks.current_app.config', {'SMTP_TEMPLATE_ID': template.id})

    ref_1 = str(uuid4())
    ref_2 = str(uuid4())
    notification = sample_notification(template=template, reference=ref_1)
    create_service_callback_api(service=notification.service, url='https://original_url.com')
    # Trouble processing smtp user with multiple workers - dao_services_by_partial_smtp_name finds multiple rows
    assert process_ses_receipts_tasks.process_ses_smtp_results(ses_smtp_soft_bounce_callback(reference=ref_2))
    assert send_mock.called


@pytest.mark.serial
def test_ses_smtp_callback_should_set_status_to_permanent_failure(
    client,
    sample_notification,
    sample_smtp_template,
    mocker,
):
    template = sample_smtp_template()
    send_mock = mocker.patch('app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async')
    mocker.patch.dict('app.celery.process_ses_receipts_tasks.current_app.config', {'SMTP_TEMPLATE_ID': template.id})

    ref = str(uuid4())
    sample_notification(template=template, reference=ref)
    create_service_callback_api(service=template.service, url='https://original_url.com')
    # Trouble processing smtp user with multiple workers - dao_services_by_partial_smtp_name finds multiple rows
    assert process_ses_receipts_tasks.process_ses_smtp_results(ses_smtp_hard_bounce_callback(reference=ref))
    assert send_mock.called


@pytest.mark.serial
def test_ses_smtp_callback_should_send_on_complaint_to_user_callback_api(
    sample_smtp_template,
    sample_template,
    sample_notification,
    mocker,
):
    template = sample_smtp_template()
    send_mock = mocker.patch('app.celery.service_callback_tasks.send_complaint_to_service.apply_async')
    mocker.patch.dict('app.celery.process_ses_receipts_tasks.current_app.config', {'SMTP_TEMPLATE_ID': template.id})

    create_service_callback_api(service=template.service, url='https://original_url.com', callback_type='complaint')

    # Generate id for multi-worker testing
    feedback_id = str(uuid4())
    sample_notification(template=template, reference=feedback_id)
    response = ses_smtp_complaint_callback(feedback_id)
    # Trouble processing smtp user with multiple workers - dao_services_by_partial_smtp_name finds multiple rows
    assert process_ses_receipts_tasks.process_ses_smtp_results(response)
    assert send_mock.call_count == 1


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


class TestSendEmailStatusToVAProfile:
    mock_notification_data = {
        'id': '2e9e6920-4f6f-4cd5-9e16-fc306fe23867',  # this is the notification id
        'reference': None,
        'to': 'test@email.com',  # this is the recipient's contact info (email)
        'status': 'delivered',  # this will specify the delivery status of the notification
        'status_reason': '',  # populated if there's additional context on the delivery status
        'created_at': '2024-07-25T10:00:00.0',
        'completed_at': '2024-07-25T11:00:00.0',
        'sent_at': '2024-07-25T11:00:00.0',
        'notification_type': EMAIL_TYPE,  # this is the channel/type of notification (email)
        'provider': 'ses',  # email provider
    }

    @pytest.fixture()
    def mock_notification(self) -> Notification:
        notification_mock = Notification()

        notification_mock.id = uuid.UUID('2e9e6920-4f6f-4cd5-9e16-fc306fe23867')
        notification_mock.client_reference = None
        notification_mock.to = 'test@email.com'
        notification_mock.status = 'delivered'
        # notification_mock.status_reason = ''
        notification_mock.created_at = datetime.fromisoformat('2024-07-25T10:00:00.0')
        notification_mock.updated_at = datetime.fromisoformat('2024-07-25T11:00:00.0')
        notification_mock.sent_at = datetime.fromisoformat('2024-07-25T11:00:00.0')
        notification_mock.notification_type = EMAIL_TYPE
        notification_mock.sent_by = 'ses'

        return notification_mock

    def test_ut_check_and_queue_va_profile_email_status_callback_does_not_queue_task_if_feature_disabled(self, mocker):
        mocker.patch('app.celery.process_ses_receipts_tasks.is_feature_enabled', return_value=False)
        mock_send_email_status = mocker.patch(
            'app.celery.process_ses_receipts_tasks.send_email_status_to_va_profile.apply_async'
        )
        mock_notification = mocker.patch('app.celery.process_ses_receipts_tasks.Notification')

        process_ses_receipts_tasks.check_and_queue_va_profile_email_status_callback(mock_notification)

        mock_send_email_status.assert_not_called()

    def test_ut_check_and_queue_va_profile_email_status_callback_queues_task_if_feature_enabled(self, mocker):
        mocker.patch('app.celery.process_ses_receipts_tasks.is_feature_enabled', return_value=True)
        mock_send_email_status = mocker.patch(
            'app.celery.process_ses_receipts_tasks.send_email_status_to_va_profile.apply_async'
        )
        mock_notification = mocker.patch('app.celery.process_ses_receipts_tasks.Notification')

        process_ses_receipts_tasks.check_and_queue_va_profile_email_status_callback(mock_notification)

        mock_send_email_status.assert_called_once()

    def test_ut_send_email_status_to_va_profile(self, mocker):
        mock_send_va_profile_email_status = mocker.patch(
            'app.celery.process_ses_receipts_tasks.va_profile_client.send_va_profile_email_status'
        )

        process_ses_receipts_tasks.send_email_status_to_va_profile(self.mock_notification_data)

        mock_send_va_profile_email_status.assert_called_once_with(self.mock_notification_data)

    def test_ut_send_email_status_to_va_profile_raises_auto_retry_exception(self, mocker):
        mock_send_va_profile_email_status = mocker.patch(
            'app.celery.process_ses_receipts_tasks.va_profile_client.send_va_profile_email_status',
            side_effect=[ConnectTimeout, ReadTimeout],
        )

        with pytest.raises(AutoRetryException):
            process_ses_receipts_tasks.send_email_status_to_va_profile(self.mock_notification_data)

        mock_send_va_profile_email_status.assert_called_once()


@pytest.mark.parametrize('status', (NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_TEMPORARY_FAILURE))
def test_process_ses_results_no_bounce_regression(
    notify_db_session,
    sample_template,
    sample_notification,
    status,
):
    """
    If a bounce status has been persisted for a notificaiton, no further status updates should occur.
    Soft bounces are temporary failures.  Hard bounces are permanent failures.
    """

    notification = sample_notification(
        template=sample_template(template_type=EMAIL_TYPE),
        status=status,
        status_reason='bounce',
        reference=str(uuid4()),
    )

    # Simulate a delivery callback arriving after the message already bounced.
    response = ses_notification_callback(notification.reference)
    assert json.loads(response['Message'])['eventType'] == 'Delivery'
    assert process_ses_receipts_tasks.process_ses_results(response) is None

    notify_db_session.session.refresh(notification)
    assert notification.status == status, 'The status should not have changed.'
    assert notification.status_reason == 'bounce'
