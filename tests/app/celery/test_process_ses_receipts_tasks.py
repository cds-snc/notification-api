import json
import pytest
from datetime import datetime
from freezegun import freeze_time
from sqlalchemy import select
from uuid import uuid4

from app import statsd_client
from app.celery import process_ses_receipts_tasks
from app.celery.research_mode_tasks import ses_hard_bounce_callback, ses_soft_bounce_callback, ses_notification_callback
from app.celery.service_callback_tasks import create_delivery_status_callback_data
from app.dao.notifications_dao import get_notification_by_id
from app.models import Complaint, EMAIL_TYPE, Notification, Service, Template
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


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_notifications_ses_400_with_invalid_header(client):
    data = json.dumps({'foo': 'bar'})
    response = client.post(path='/notifications/email/ses', data=data, headers=[('Content-Type', 'application/json')])
    assert response.status_code == 400


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_notifications_ses_400_with_invalid_message_type(client):
    data = json.dumps({'foo': 'bar'})
    response = client.post(
        path='/notifications/email/ses',
        data=data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'foo')],
    )
    assert response.status_code == 400
    assert 'SES-SNS callback failed: invalid message type' in response.get_data(as_text=True)


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_notifications_ses_400_with_invalid_json(client):
    data = 'FOOO'
    response = client.post(
        path='/notifications/email/ses',
        data=data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'Notification')],
    )
    assert response.status_code == 400
    assert 'SES-SNS callback failed: invalid JSON given' in response.get_data(as_text=True)


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_notifications_ses_400_with_certificate(client):
    data = json.dumps({'foo': 'bar'})
    response = client.post(
        path='/notifications/email/ses',
        data=data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'Notification')],
    )
    assert response.status_code == 400
    assert 'SES-SNS callback failed: validation failed' in response.get_data(as_text=True)


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_notifications_ses_200_autoconfirms_subscription(client, mocker):
    mocker.patch('validatesns.validate')
    requests_mock = mocker.patch('requests.get')
    data = json.dumps({'Type': 'SubscriptionConfirmation', 'SubscribeURL': 'https://foo'})
    response = client.post(
        path='/notifications/email/ses',
        data=data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'SubscriptionConfirmation')],
    )

    requests_mock.assert_called_once_with('https://foo')
    assert response.status_code == 200


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_notifications_ses_200_call_process_task(client, mocker):
    mocker.patch('validatesns.validate')
    process_mock = mocker.patch('app.celery.process_ses_receipts_tasks.process_ses_results.apply_async')
    data = {'Type': 'Notification', 'foo': 'bar'}
    json_data = json.dumps(data)
    response = client.post(
        path='/notifications/email/ses',
        data=json_data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'Notification')],
    )

    process_mock.assert_called_once_with([{'Message': None}], queue='notify-internal-tasks')
    assert response.status_code == 200


def test_process_ses_results(sample_template, sample_notification):
    template = sample_template(template_type=EMAIL_TYPE)
    ref = str(uuid4())
    sample_notification(template=template, reference=ref, sent_at=datetime.utcnow(), status='sending')

    assert process_ses_receipts_tasks.process_ses_results(response=ses_notification_callback(reference=ref))


def test_process_ses_results_retry_called(mocker, sample_template, sample_notification):
    template = sample_template(template_type=EMAIL_TYPE)
    ref = str(uuid4())
    sample_notification(template=template, reference=ref, sent_at=datetime.utcnow(), status='sending')

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


def test_ses_callback_should_call_send_delivery_status_to_service(mocker, client, sample_template, sample_notification):
    send_mock = mocker.patch('app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async')

    template = sample_template(template_type=EMAIL_TYPE)
    ref = str(uuid4())
    notification = sample_notification(template=template, status='sending', reference=ref)

    service_callback = create_service_callback_api(service=template.service, url='https://original_url.com')

    process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference=ref))

    updated_notification = Notification.query.get(notification.id)

    encrypted_data = create_delivery_status_callback_data(updated_notification, service_callback)
    send_mock.assert_called_once_with(
        [service_callback.id, str(notification.id), encrypted_data], queue='service-callbacks'
    )


def test_ses_callback_should_send_statsd_statistics(mocker, client, sample_template, sample_notification):
    template = sample_template(template_type=EMAIL_TYPE)
    with freeze_time('2001-01-01T12:00:00'):
        mocker.patch('app.statsd_client.incr')
        mocker.patch('app.statsd_client.timing_with_dates')

        ref = str(uuid4())
        notification = sample_notification(template=template, status='sending', reference=ref)
        process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference=ref))

        statsd_client.timing_with_dates.assert_any_call(
            'callback.ses.elapsed-time', datetime.utcnow(), notification.sent_at
        )
        statsd_client.incr.assert_any_call('callback.ses.delivered')


def test_ses_callback_should_not_update_notification_status_if_already_delivered(
    mocker, sample_template, sample_notification
):
    mock_dup = mocker.patch('app.celery.process_ses_receipts_tasks.notifications_dao.duplicate_update_warning')
    mock_upd = mocker.patch('app.celery.process_ses_receipts_tasks.notifications_dao._update_notification_status')

    template = sample_template(template_type=EMAIL_TYPE)
    ref = str(uuid4())
    notification = sample_notification(template=template, reference=ref, status='delivered')

    assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference=ref)) is None
    assert get_notification_by_id(notification.id).status == 'delivered'

    mock_dup.assert_called_once()
    assert mock_dup.call_args.args[0].id == notification.id
    assert mock_dup.call_args.args[1] == 'delivered'
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
            'notification not found for reference: %s (update to %s)', ref, 'delivered'
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
        notification_id = sample_notification(template=template, status='sending', reference=ref).id

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
        status='sending',
        reference='ref1',
    )
    sample_notification(
        template=template,
        status='sending',
        reference='ref2',
    )
    sample_notification(
        template=template,
        status='sending',
        reference='ref3',
    )
    create_service_callback_api(service=template.service, url='https://original_url.com')
    assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference='ref1'))
    assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference='ref2'))
    assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference='ref3'))
    assert send_mock.called


def test_ses_callback_should_set_status_to_temporary_failure(client, mocker, sample_template, sample_notification):
    send_mock = mocker.patch('app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async')

    template = sample_template(template_type=EMAIL_TYPE)
    ref = str(uuid4())
    notification_id = sample_notification(
        template=template,
        status='sending',
        reference=ref,
    ).id

    create_service_callback_api(service=template.service, url='https://original_url.com')

    assert process_ses_receipts_tasks.process_ses_results(ses_soft_bounce_callback(reference=ref))
    assert get_notification_by_id(notification_id).status == 'temporary-failure'
    assert (
        get_notification_by_id(notification_id).status_reason
        == 'Temporarily failed to deliver email due to soft bounce'
    )
    assert send_mock.called


def test_ses_callback_should_set_status_to_permanent_failure(client, mocker, sample_template, sample_notification):
    send_mock = mocker.patch('app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async')

    template = sample_template(template_type=EMAIL_TYPE)
    ref = str(uuid4())
    notification_id = sample_notification(
        template=template,
        status='sending',
        reference=ref,
    ).id
    create_service_callback_api(service=template.service, url='https://original_url.com')

    assert get_notification_by_id(notification_id).status == 'sending'
    assert process_ses_receipts_tasks.process_ses_results(ses_hard_bounce_callback(reference=ref))
    assert get_notification_by_id(notification_id).status == 'permanent-failure'
    assert get_notification_by_id(notification_id).status_reason == 'Failed to deliver email due to hard bounce'
    assert send_mock.called


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_notifications_ses_smtp_400_with_invalid_header(client):
    data = json.dumps({'foo': 'bar'})
    response = client.post(
        path='/notifications/email/ses-smtp', data=data, headers=[('Content-Type', 'application/json')]
    )
    assert response.status_code == 400


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_notifications_ses_smtp_400_with_invalid_message_type(client):
    data = json.dumps({'foo': 'bar'})
    response = client.post(
        path='/notifications/email/ses-smtp',
        data=data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'foo')],
    )
    assert response.status_code == 400
    assert 'SES-SNS SMTP callback failed: invalid message type' in response.get_data(as_text=True)


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_notifications_ses_smtp_400_with_invalid_json(client):
    data = 'FOOO'
    response = client.post(
        path='/notifications/email/ses-smtp',
        data=data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'Notification')],
    )
    assert response.status_code == 400
    assert 'SES-SNS SMTP callback failed: invalid JSON given' in response.get_data(as_text=True)


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_notifications_ses_smtp_400_with_certificate(client):
    data = json.dumps({'foo': 'bar'})
    response = client.post(
        path='/notifications/email/ses-smtp',
        data=data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'Notification')],
    )
    assert response.status_code == 400
    assert 'SES-SNS SMTP callback failed: validation failed' in response.get_data(as_text=True)


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_notifications_ses_smtp_200_autoconfirms_subscription(client, mocker):
    mocker.patch('validatesns.validate')
    requests_mock = mocker.patch('requests.get')
    data = json.dumps({'Type': 'SubscriptionConfirmation', 'SubscribeURL': 'https://foo'})
    response = client.post(
        path='/notifications/email/ses-smtp',
        data=data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'SubscriptionConfirmation')],
    )

    requests_mock.assert_called_once_with('https://foo')
    assert response.status_code == 200


@pytest.mark.skip(reason='Endpoint disabled and slated for removal')
def test_notifications_ses_smtp_200_call_process_task(client, mocker):
    mocker.patch('validatesns.validate')
    process_mock = mocker.patch('app.celery.process_ses_receipts_tasks.process_ses_smtp_results.apply_async')
    data = {'Type': 'Notification', 'foo': 'bar'}
    json_data = json.dumps(data)
    response = client.post(
        path='/notifications/email/ses-smtp',
        data=json_data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'Notification')],
    )

    process_mock.assert_called_once_with([{'Message': None}], queue='notify-internal-tasks')
    assert response.status_code == 200


def test_process_ses_smtp_results(
    sample_smtp_template,
    mocker,
):
    template = sample_smtp_template()
    mocker.patch.dict('app.celery.process_ses_receipts_tasks.current_app.config', {'SMTP_TEMPLATE_ID': template.id})
    assert process_ses_receipts_tasks.process_ses_smtp_results(response=ses_smtp_notification_callback())


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
    process_ses_receipts_tasks.process_ses_smtp_results(response=ses_smtp_complaint_callback(feedback_id))
    assert mocked.call_count == 0

    stmt = select(Complaint).where(Complaint.feedback_id == feedback_id)
    complaints = notify_db_session.session.scalars(stmt).all()
    assert len(complaints) == 1


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
    assert process_ses_receipts_tasks.process_ses_smtp_results(ses_smtp_soft_bounce_callback(reference=ref_2))
    assert send_mock.called


def test_ses_smtp_callback_should_set_status_to_permanent_failure(
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
    sample_notification(template=template, reference=ref_1)
    create_service_callback_api(service=template.service, url='https://original_url.com')
    assert process_ses_receipts_tasks.process_ses_smtp_results(ses_smtp_hard_bounce_callback(reference=ref_2))
    assert send_mock.called


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

    sample_notification(template=template, reference='ref1')
    response = ses_smtp_complaint_callback()
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
        status='sending',
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
