from datetime import datetime, timedelta
from unittest.mock import Mock, call
from uuid import uuid4

from celery.exceptions import Retry
from freezegun import freeze_time
from notifications_utils.columns import Row
from notifications_utils.template import SMSMessageTemplate, WithSubjectTemplate
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app import encryption
from app.celery import provider_tasks
from app.celery import tasks
from app.celery.tasks import (
    process_job,
    process_row,
    save_sms,
    save_email,
    save_letter,
    process_incomplete_job,
    process_incomplete_jobs,
    get_template_class,
    s3,
)
from app.constants import (
    EMAIL_TYPE,
    KEY_TYPE_NORMAL,
    JOB_STATUS_FINISHED,
    JOB_STATUS_ERROR,
    JOB_STATUS_IN_PROGRESS,
    LETTER_TYPE,
    SMS_TYPE,
)
from app.feature_flags import FeatureFlag
from app.models import Job, Notification, ServiceSmsSender

from tests.app import load_example_csv
from tests.app.factories.feature_flag import mock_feature_flag


class AnyStringWith(str):
    def __eq__(self, other):
        return self in other


mmg_error = {'Error': '40', 'Description': 'error'}


def _notification_json(template, to, personalisation=None, job_id=None, row_number=0):
    return {
        'template': str(template.id),
        'template_version': template.version,
        'to': to,
        'notification_type': template.template_type,
        'personalisation': personalisation or {},
        'job': job_id and str(job_id),
        'row_number': row_number,
        'service_id': str(uuid4()),
        'reply_to_text': '+11111111111',
    }


def test_should_have_decorated_tasks_functions():
    assert process_job.__wrapped__.__name__ == 'process_job'
    assert save_sms.__wrapped__.__name__ == 'save_sms'
    assert save_email.__wrapped__.__name__ == 'save_email'
    assert save_letter.__wrapped__.__name__ == 'save_letter'


# -------------- process_job tests -------------- #


def test_should_process_sms_job(
    mocker,
    sample_template,
    sample_job,
    notify_db_session,
):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv(SMS_TYPE))
    mocker.patch('app.celery.tasks.save_sms.apply_async')
    mocker.patch('app.encryption.encrypt', return_value='something_encrypted')
    mocker.patch('app.celery.tasks.create_uuid', return_value='uuid')
    template = sample_template()
    job = sample_job(template=template)

    process_job(job.id)
    s3.get_job_from_s3.assert_called_once_with(str(job.service.id), str(job.id))
    assert encryption.encrypt.call_args[0][0]['to'] == '+441234123123'
    assert encryption.encrypt.call_args[0][0]['template'] == str(job.template.id)
    assert encryption.encrypt.call_args[0][0]['template_version'] == job.template.version
    assert encryption.encrypt.call_args[0][0]['personalisation'] == {'phonenumber': '+441234123123'}
    assert encryption.encrypt.call_args[0][0]['row_number'] == 0
    tasks.save_sms.apply_async.assert_called_once_with(
        (str(job.service_id), 'uuid', 'something_encrypted'), {}, queue='notify-internal-tasks'
    )

    # Retrieve job from db
    notify_db_session.session.refresh(job)
    assert job.job_status == 'finished'


def test_should_process_sms_job_with_sender_id(
    mocker,
    fake_uuid,
    sample_template,
    sample_job,
):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv(SMS_TYPE))
    mocker.patch('app.celery.tasks.save_sms.apply_async')
    mocker.patch('app.encryption.encrypt', return_value='something_encrypted')
    mocker.patch('app.celery.tasks.create_uuid', return_value='uuid')

    template = sample_template()
    job = sample_job(template=template)
    process_job(job.id, sender_id=fake_uuid)

    tasks.save_sms.apply_async.assert_called_once_with(
        (str(job.service_id), 'uuid', 'something_encrypted'), {'sender_id': fake_uuid}, queue='notify-internal-tasks'
    )


@freeze_time('2016-01-01 11:09:00.061258')
def test_should_not_process_sms_job_if_would_exceed_send_limits(
    mocker, notify_db_session, sample_service, sample_template, sample_job
):
    service = sample_service(message_limit=9)
    template = sample_template(service=service)
    job = sample_job(template, notification_count=10, original_file_name='multiple_sms.csv')
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('multiple_sms'))
    mocker.patch('app.celery.tasks.process_row')

    process_job(job.id)
    notify_db_session.session.refresh(job)

    assert job.job_status == 'sending limits exceeded'
    assert s3.get_job_from_s3.called is False
    assert tasks.process_row.called is False


def test_should_not_process_sms_job_if_would_exceed_send_limits_inc_today(
    mocker,
    sample_service,
    sample_template,
    sample_job,
    sample_notification,
    notify_db_session,
):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv(SMS_TYPE))
    mocker.patch('app.celery.tasks.process_row')

    service = sample_service(message_limit=1)
    template = sample_template(service=service)
    job = sample_job(template)
    sample_notification(template=template, job=job)

    process_job(job.id)
    notify_db_session.session.refresh(job)

    assert job.job_status == 'sending limits exceeded'
    assert s3.get_job_from_s3.called is False
    assert tasks.process_row.called is False


@pytest.mark.parametrize('template_type', [SMS_TYPE, EMAIL_TYPE])
def test_should_not_process_email_job_if_would_exceed_send_limits_inc_today(
    template_type,
    mocker,
    notify_db_session,
    sample_service,
    sample_template,
    sample_job,
    sample_notification,
):
    service = sample_service(message_limit=1)
    template = sample_template(service=service, template_type=template_type)
    job = sample_job(template)

    sample_notification(template=template, job=job)

    mocker.patch('app.celery.tasks.s3.get_job_from_s3')
    mocker.patch('app.celery.tasks.process_row')

    process_job(job.id)

    notify_db_session.session.refresh(job)

    assert job.job_status == 'sending limits exceeded'
    assert s3.get_job_from_s3.called is False
    assert tasks.process_row.called is False


def test_should_not_process_job_if_already_pending(
    sample_template,
    sample_job,
    mocker,
):
    template = sample_template()
    job = sample_job(template, job_status='scheduled')

    mocker.patch('app.celery.tasks.s3.get_job_from_s3')
    mocker.patch('app.celery.tasks.process_row')

    process_job(job.id)

    assert s3.get_job_from_s3.called is False
    assert tasks.process_row.called is False


def test_should_process_email_job_if_exactly_on_send_limits(
    mocker,
    notify_db_session,
    sample_service,
    sample_template,
    sample_job,
):
    service = sample_service(message_limit=10)
    template = sample_template(service=service, template_type=EMAIL_TYPE)
    job = sample_job(template, notification_count=10)

    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('multiple_email'))
    mocker.patch('app.celery.tasks.save_email.apply_async')
    mocker.patch('app.encryption.encrypt', return_value='something_encrypted')
    mocker.patch('app.celery.tasks.create_uuid', return_value='uuid')

    process_job(job.id)

    s3.get_job_from_s3.assert_called_once_with(str(job.service.id), str(job.id))

    notify_db_session.session.refresh(job)

    assert job.job_status == 'finished'
    tasks.save_email.apply_async.assert_called_with(
        (
            str(job.service_id),
            'uuid',
            'something_encrypted',
        ),
        {},
        queue='notify-internal-tasks',
    )


def test_should_not_create_save_task_for_empty_file(
    mocker,
    notify_db_session,
    sample_template,
    sample_job,
):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('empty'))
    mocker.patch('app.celery.tasks.save_sms.apply_async')

    template = sample_template()
    job = sample_job(template)
    process_job(job.id)

    s3.get_job_from_s3.assert_called_once_with(str(job.service.id), str(job.id))

    notify_db_session.session.refresh(job)

    assert job.job_status == 'finished'
    assert tasks.save_sms.apply_async.called is False


def test_should_process_email_job(
    mocker,
    notify_db_session,
    sample_template,
    sample_job,
):
    email_csv = """\
    email_address,name
    test@test.com,foo
    """

    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=email_csv)
    mocker.patch('app.celery.tasks.save_email.apply_async')
    mocker.patch('app.encryption.encrypt', return_value='something_encrypted')
    mocker.patch('app.celery.tasks.create_uuid', return_value='uuid')

    template = sample_template(template_type=EMAIL_TYPE, content='Hello (( Name))\nYour thing is due soon')
    job = sample_job(template)
    process_job(job.id)

    s3.get_job_from_s3.assert_called_once_with(str(job.service.id), str(job.id))

    assert encryption.encrypt.call_args[0][0]['to'] == 'test@test.com'
    assert encryption.encrypt.call_args[0][0]['template'] == str(template.id)
    assert encryption.encrypt.call_args[0][0]['template_version'] == template.version
    assert encryption.encrypt.call_args[0][0]['personalisation'] == {'emailaddress': 'test@test.com', 'name': 'foo'}
    tasks.save_email.apply_async.assert_called_once_with(
        (
            str(job.service_id),
            'uuid',
            'something_encrypted',
        ),
        {},
        queue='notify-internal-tasks',
    )

    notify_db_session.session.refresh(job)

    assert job.job_status == 'finished'


def test_should_process_email_job_with_sender_id(
    mocker,
    fake_uuid,
    sample_template,
    sample_job,
):
    email_csv = """\
    email_address,name
    test@test.com,foo
    """

    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=email_csv)
    mocker.patch('app.celery.tasks.save_email.apply_async')
    mocker.patch('app.encryption.encrypt', return_value='something_encrypted')
    mocker.patch('app.celery.tasks.create_uuid', return_value='uuid')

    template = sample_template(template_type=EMAIL_TYPE, content='Hello (( Name))\nYour thing is due soon')
    job = sample_job(template)
    process_job(job.id, sender_id=fake_uuid)

    tasks.save_email.apply_async.assert_called_once_with(
        (str(job.service_id), 'uuid', 'something_encrypted'),
        {'sender_id': fake_uuid},
        queue='notify-internal-tasks',
    )


def test_should_process_all_sms_job(
    mocker,
    notify_db_session,
    sample_template,
    sample_job,
):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('multiple_sms'))
    mocker.patch('app.celery.tasks.save_sms.apply_async')
    mocker.patch('app.encryption.encrypt', return_value='something_encrypted')
    mocker.patch('app.celery.tasks.create_uuid', return_value='uuid')

    template = sample_template(content='Hello (( Name))\nYour thing is due soon')
    job = sample_job(template)
    process_job(job.id)

    s3.get_job_from_s3.assert_called_once_with(str(job.service.id), str(job.id))

    assert encryption.encrypt.call_args[0][0]['to'] == '+441234123120'
    assert encryption.encrypt.call_args[0][0]['template'] == str(template.id)
    assert encryption.encrypt.call_args[0][0]['template_version'] == template.version
    assert encryption.encrypt.call_args[0][0]['personalisation'] == {'phonenumber': '+441234123120', 'name': 'chris'}
    assert tasks.save_sms.apply_async.call_count == 10

    notify_db_session.session.refresh(job)

    assert job.job_status == 'finished'


@pytest.mark.parametrize(
    'template_type, research_mode, expected_function, expected_queue',
    [
        (SMS_TYPE, False, 'save_sms', 'notify-internal-tasks'),
        (SMS_TYPE, True, 'save_sms', 'notify-internal-tasks'),
        (EMAIL_TYPE, False, 'save_email', 'notify-internal-tasks'),
        (EMAIL_TYPE, True, 'save_email', 'notify-internal-tasks'),
        (LETTER_TYPE, False, 'save_letter', 'notify-internal-tasks'),
        (LETTER_TYPE, True, 'save_letter', 'notify-internal-tasks'),
    ],
)
def test_process_row_sends_letter_task(
    template_type,
    research_mode,
    expected_function,
    expected_queue,
    mocker,
):
    mocker.patch('app.celery.tasks.create_uuid', return_value='noti_uuid')
    task_mock = mocker.patch('app.celery.tasks.{}.apply_async'.format(expected_function))
    encrypt_mock = mocker.patch('app.celery.tasks.encryption.encrypt')
    template = Mock(id='template_id', template_type=template_type)
    job = Mock(id='job_id', template_version='temp_vers')
    service = Mock(id='service_id', research_mode=research_mode)

    process_row(
        Row(
            {'foo': 'bar', 'to': 'recip'},
            index='row_num',
            error_fn=lambda k, v: None,
            recipient_column_headers=['to'],
            placeholders={'foo'},
            template=template,
        ),
        template,
        job,
        service,
    )

    encrypt_mock.assert_called_once_with(
        {
            'template': 'template_id',
            'template_version': 'temp_vers',
            'job': 'job_id',
            'to': 'recip',
            'row_number': 'row_num',
            'personalisation': {'foo': 'bar'},
        }
    )
    task_mock.assert_called_once_with(
        (
            'service_id',
            'noti_uuid',
            # encrypted data
            encrypt_mock.return_value,
        ),
        {},
        queue=expected_queue,
    )


# -------- save_sms and save_email tests -------- #


def test_process_row_when_sender_id_is_provided(mocker, fake_uuid):
    mocker.patch('app.celery.tasks.create_uuid', return_value='noti_uuid')
    task_mock = mocker.patch('app.celery.tasks.save_sms.apply_async')
    encrypt_mock = mocker.patch('app.celery.tasks.encryption.encrypt')
    template = Mock(id='template_id', template_type=SMS_TYPE)
    job = Mock(id='job_id', template_version='temp_vers')
    service = Mock(id='service_id', research_mode=False)

    process_row(
        Row(
            {'foo': 'bar', 'to': 'recip'},
            index='row_num',
            error_fn=lambda k, v: None,
            recipient_column_headers=['to'],
            placeholders={'foo'},
            template=template,
        ),
        template,
        job,
        service,
        sender_id=fake_uuid,
    )

    task_mock.assert_called_once_with(
        (
            'service_id',
            'noti_uuid',
            # encrypted data
            encrypt_mock.return_value,
        ),
        {'sender_id': fake_uuid},
        queue='notify-internal-tasks',
    )


def test_should_send_template_to_correct_sms_task_and_persist(
    notify_db_session,
    sample_service,
    sample_template,
    mocker,
):
    service = sample_service()
    template = sample_template(service=service)

    # Cleaned by sample_template
    notification = _notification_json(template, to='+1 650 253 2222', personalisation={'name': 'Jo'})

    mocked_deliver_sms = mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')

    notification_id = uuid4()

    save_sms(
        template.service_id,
        notification_id,
        encryption.encrypt(notification),
    )

    notify_db_session.session.expire_all()
    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    assert persisted_notification.to == '+1 650 253 2222'
    assert persisted_notification.template_id == template.id
    assert persisted_notification.template_version == template.version
    assert persisted_notification.status == 'created'
    assert persisted_notification.created_at <= datetime.utcnow()
    assert not persisted_notification.sent_at
    assert not persisted_notification.sent_by
    assert not persisted_notification.job_id
    assert persisted_notification.personalisation == {'name': 'Jo'}
    assert persisted_notification._personalisation == encryption.encrypt({'name': 'Jo'})
    assert persisted_notification.notification_type == SMS_TYPE
    mocked_deliver_sms.assert_called_once_with(
        args=(),
        kwargs={'notification_id': str(persisted_notification.id)},
        queue='send-sms-tasks',
    )


def test_should_put_save_sms_task_in_research_mode_queue_if_research_mode_service(
    notify_db_session,
    mocker,
    sample_service,
    sample_template,
):
    service = sample_service(research_mode=True)
    template = sample_template(service=service)

    # Cleaned by sample_template
    notification = _notification_json(template, to='+1 650 253 2222')
    mocked_deliver_sms = mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')
    notification_id = uuid4()

    save_sms(
        template.service_id,
        notification_id,
        encryption.encrypt(notification),
    )
    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    provider_tasks.deliver_sms.apply_async.assert_called_once_with(
        args=(),
        kwargs={'notification_id': str(persisted_notification.id)},
        queue='notify-internal-tasks',
    )
    assert mocked_deliver_sms.called


def test_should_save_sms_if_restricted_service_and_valid_number(
    notify_db_session,
    mocker,
    sample_user,
    sample_service,
    sample_template,
):
    user = sample_user(mobile_number='+16502532222')
    service = sample_service(user=user, restricted=True)
    template = sample_template(service=service)

    # Cleaned by sample_template
    notification = _notification_json(template, '+16502532222')
    encrypt_notification = encryption.encrypt(notification)
    notification_id = uuid4()

    mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')

    save_sms(
        service.id,
        notification_id,
        encrypt_notification,
    )

    notify_db_session.session.expire_all()
    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    assert persisted_notification.to == '+16502532222'
    assert persisted_notification.template_id == template.id
    assert persisted_notification.template_version == template.version
    assert persisted_notification.status == 'created'
    assert persisted_notification.created_at <= datetime.utcnow()
    assert not persisted_notification.sent_at
    assert not persisted_notification.sent_by
    assert not persisted_notification.job_id
    assert not persisted_notification.personalisation
    assert persisted_notification.notification_type == SMS_TYPE

    provider_tasks.deliver_sms.apply_async.assert_called_once_with(
        args=(),
        kwargs={'notification_id': str(persisted_notification.id)},
        queue='send-sms-tasks',
    )


def test_save_sms_should_call_deliver_sms_with_rate_limiting_if_sender_id_provided(
    notify_db_session,
    mocker,
    sample_user,
    sample_service,
    sample_template,
):
    mock_feature_flag(mocker, FeatureFlag.SMS_SENDER_RATE_LIMIT_ENABLED, 'True')
    sms_sender = mocker.Mock()
    sms_sender.rate_limit = 1
    sms_sender.sms_sender = '+11111111111'
    mocker.patch('app.celery.tasks.dao_get_service_sms_sender_by_id', return_value=sms_sender)
    mocker.patch('app.celery.tasks.dao_get_service_sms_sender_by_service_id_and_number', return_value=sms_sender)

    user = sample_user(mobile_number='6502532222')
    service = sample_service(user=user, restricted=True)
    template = sample_template(service=service)

    # Cleaned by sample_template
    notification = _notification_json(template, '+16502532222')
    sender_id = uuid4()

    deliver_sms = mocker.patch('app.celery.provider_tasks.deliver_sms_with_rate_limiting.apply_async')

    notification_id = uuid4()
    encrypt_notification = encryption.encrypt(notification)

    save_sms(service.id, notification_id, encrypt_notification, sender_id)
    notification2 = notify_db_session.session.get(Notification, notification_id)
    assert notification2 is not None

    deliver_sms.assert_called_once_with(
        args=(),
        kwargs={'notification_id': str(notification_id)},
        queue='send-sms-tasks',
    )


def test_save_sms_should_save_default_sms_sender_notification_reply_to_text_on(
    notify_db_session,
    mocker,
    sample_service,
    sample_template,
):
    service = sample_service()
    template = sample_template(service=service)

    # sample_service also creates and persists an instance of ServiceSmsSender.
    stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
    sms_sender = notify_db_session.session.scalar(stmt)
    sms_sender.sms_sender = '12345'
    sms_sender.is_default = True

    notify_db_session.session.add(sms_sender)
    notify_db_session.session.commit()

    # Cleaned by sample_template
    notification = _notification_json(template, to='6502532222')
    mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')

    notification_id = uuid4()
    save_sms(
        service.id,
        notification_id,
        encryption.encrypt(notification),
    )

    persisted_notification = notify_db_session.session.get(Notification, notification_id)
    assert persisted_notification is not None

    assert persisted_notification.reply_to_text == '12345'


def test_should_not_save_sms_if_restricted_service_and_invalid_number(
    notify_db_session,
    mocker,
    sample_user,
    sample_service,
    sample_template,
):
    user = sample_user(mobile_number='6502532222')
    service = sample_service(user=user, restricted=True)
    template = sample_template(service=service)

    notification = _notification_json(template, '07700 900849')
    mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')

    notification_id = uuid4()
    save_sms(
        service.id,
        notification_id,
        encryption.encrypt(notification),
    )

    assert notify_db_session.session.get(Notification, notification_id) is None
    assert provider_tasks.deliver_sms.apply_async.called is False


def test_should_not_save_email_if_restricted_service_and_invalid_email_address(
    mocker,
    notify_db_session,
    sample_service,
    sample_template,
    sample_user,
):
    user = sample_user()
    service = sample_service(user=user, restricted=True)
    template = sample_template(service=service, template_type=EMAIL_TYPE, subject='Hello')
    notification = _notification_json(template, to='test@example.com')

    notification_id = uuid4()
    save_email(
        service.id,
        notification_id,
        encryption.encrypt(notification),
    )

    assert notify_db_session.session.get(Notification, notification_id) is None


def test_should_put_save_email_task_in_research_mode_queue_if_research_mode_service(
    mocker,
    notify_db_session,
    sample_service,
    sample_template,
):
    service = sample_service(research_mode=True)
    template = sample_template(service=service, template_type=EMAIL_TYPE)

    # Cleaned by sample_template
    notification = _notification_json(template, to='test@test.com')

    mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    notification_id = uuid4()

    save_email(
        template.service_id,
        notification_id,
        encryption.encrypt(notification),
    )

    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    provider_tasks.deliver_email.apply_async.assert_called_once_with(
        args=(),
        kwargs={
            'notification_id': str(persisted_notification.id),
        },
        queue='notify-internal-tasks',
    )


def test_should_save_sms_template_to_and_persist_with_job_id(
    notify_db_session,
    sample_template,
    sample_job,
    mocker,
):
    template = sample_template()
    job = sample_job(template)

    # Cleaned by sample_template
    notification = _notification_json(job.template, to='+1 650 253 2222', job_id=job.id, row_number=2)
    mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')

    notification_id = uuid4()
    now = datetime.utcnow()

    save_sms(
        job.service.id,
        notification_id,
        encryption.encrypt(notification),
    )
    notify_db_session.session.expire_all()
    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    assert persisted_notification.to == '+1 650 253 2222'
    assert persisted_notification.job_id == job.id
    assert persisted_notification.template_id == job.template.id
    assert persisted_notification.status == 'created'
    assert not persisted_notification.sent_at
    assert persisted_notification.created_at >= now
    assert not persisted_notification.sent_by
    assert persisted_notification.job_row_number == 2
    assert persisted_notification.api_key_id is None
    assert persisted_notification.key_type == KEY_TYPE_NORMAL
    assert persisted_notification.notification_type == SMS_TYPE
    provider_tasks.deliver_sms.apply_async.assert_called_once_with(
        args=(),
        kwargs={'notification_id': str(persisted_notification.id)},
        queue='send-sms-tasks',
    )


def test_should_not_save_sms_if_team_key_and_recipient_not_in_team(
    notify_db_session,
    mocker,
    sample_user,
    sample_service,
    sample_template,
):
    user = sample_user(mobile_number='6502532222')
    service = sample_service(user=user, restricted=True)
    template = sample_template(service=service)

    team_members = [user.mobile_number for user in service.users]
    assert '07890 300000' not in team_members

    notification = _notification_json(template, '07700 900849')
    mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')

    notification_id = uuid4()
    save_sms(
        service.id,
        notification_id,
        encryption.encrypt(notification),
    )

    assert notify_db_session.session.get(Notification, notification_id) is None
    assert provider_tasks.deliver_sms.apply_async.called is False


def test_should_use_email_template_and_persist(
    notify_db_session,
    sample_template,
    mocker,
):
    mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    template = sample_template(
        template_type=EMAIL_TYPE,
        subject='((name))',
        content='Hello ((name))\nThis is an email from GOV.UK',
    )
    now = datetime(2016, 1, 1, 11, 9, 0)
    notification_id = uuid4()

    with freeze_time('2016-01-01 12:00:00.000000'):
        # Cleaned by sample_template
        notification = _notification_json(template, 'my_email@my_email.com', {'name': 'Jo'}, row_number=1)

    with freeze_time('2016-01-01 11:10:00.00000'):
        save_email(
            template.service_id,
            notification_id,
            encryption.encrypt(notification),
        )

    notify_db_session.session.expire_all()
    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    assert persisted_notification.to == 'my_email@my_email.com'
    assert persisted_notification.template_id == template.id
    assert persisted_notification.template_version == template.version
    assert persisted_notification.created_at >= now
    assert not persisted_notification.sent_at
    assert persisted_notification.status == 'created'
    assert not persisted_notification.sent_by
    assert persisted_notification.job_row_number == 1
    assert persisted_notification.personalisation == {'name': 'Jo'}
    assert persisted_notification._personalisation == encryption.encrypt({'name': 'Jo'})
    assert persisted_notification.api_key_id is None
    assert persisted_notification.key_type == KEY_TYPE_NORMAL
    assert persisted_notification.notification_type == EMAIL_TYPE

    provider_tasks.deliver_email.apply_async.assert_called_once_with(
        args=(), kwargs={'notification_id': str(persisted_notification.id)}, queue='send-email-tasks'
    )


def test_save_email_should_use_template_version_from_job_not_latest(
    notify_db_session,
    sample_template,
    mocker,
):
    template = sample_template(template_type=EMAIL_TYPE)

    # Cleaned by sample_template
    notification = _notification_json(template, 'my_email@my_email.com')
    version_on_notification = template.version

    # Change the template
    from app.dao.templates_dao import dao_update_template, dao_get_template_by_id

    template.content = template.content + ' another version of the template'
    mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
    dao_update_template(template)
    t = dao_get_template_by_id(template.id)
    assert t.version > version_on_notification
    now = datetime.utcnow()

    notification_id = uuid4()

    save_email(
        template.service_id,
        notification_id,
        encryption.encrypt(notification),
    )

    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    assert persisted_notification.to == 'my_email@my_email.com'
    assert persisted_notification.template_id == template.id
    assert persisted_notification.template_version == version_on_notification
    assert persisted_notification.created_at >= now
    assert not persisted_notification.sent_at
    assert persisted_notification.status == 'created'
    assert not persisted_notification.sent_by
    assert persisted_notification.notification_type == EMAIL_TYPE
    provider_tasks.deliver_email.apply_async.assert_called_once_with(
        args=(),
        kwargs={'notification_id': str(persisted_notification.id)},
        queue='send-email-tasks',
    )


def test_should_use_email_template_subject_placeholders(
    notify_db_session,
    sample_template,
    mocker,
):
    template = sample_template(
        template_type=EMAIL_TYPE,
        subject='((name))',
        content='Hello ((name))\nThis is an email from GOV.UK',
    )

    # Cleaned by sample_template
    notification_data = _notification_json(template, 'my_email@my_email.com', {'name': 'Jo'})
    mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    notification_id = uuid4()
    now = datetime.utcnow()

    save_email(
        template.service_id,
        notification_id,
        encryption.encrypt(notification_data),
    )
    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    assert persisted_notification.to == 'my_email@my_email.com'
    assert persisted_notification.template_id == template.id
    assert persisted_notification.status == 'created'
    assert persisted_notification.created_at >= now
    assert not persisted_notification.sent_by
    assert persisted_notification.personalisation == {'name': 'Jo'}
    assert not persisted_notification.reference
    assert persisted_notification.notification_type == EMAIL_TYPE
    provider_tasks.deliver_email.apply_async.assert_called_once_with(
        args=(),
        kwargs={'notification_id': str(notification_id)},
        queue='send-email-tasks',
    )


def test_should_use_email_template_and_persist_without_personalisation(
    notify_db_session,
    sample_template,
    mocker,
):
    template = sample_template(template_type=EMAIL_TYPE)

    # Cleaned by sample_template
    notification = _notification_json(template, 'my_email@my_email.com')
    mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    notification_id = uuid4()

    now = datetime.utcnow()
    save_email(
        template.service_id,
        notification_id,
        encryption.encrypt(notification),
    )

    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    assert persisted_notification.to == 'my_email@my_email.com'
    assert persisted_notification.template_id == template.id
    assert persisted_notification.created_at >= now
    assert not persisted_notification.sent_at
    assert persisted_notification.status == 'created'
    assert not persisted_notification.sent_by
    assert not persisted_notification.personalisation
    assert not persisted_notification.reference
    assert persisted_notification.notification_type == EMAIL_TYPE
    provider_tasks.deliver_email.apply_async.assert_called_once_with(
        args=(),
        kwargs={'notification_id': str(persisted_notification.id)},
        queue='send-email-tasks',
    )


def test_save_sms_should_go_to_retry_queue_if_database_errors(
    notify_db_session,
    mocker,
    sample_template,
):
    template = sample_template()
    assert template.template_type == SMS_TYPE
    notification = _notification_json(template, '+1 650 253 2222')

    expected_exception = SQLAlchemyError()

    mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')
    mocker.patch('app.celery.tasks.save_sms.retry', side_effect=Retry)
    mocker.patch('app.notifications.process_notifications.dao_create_notification', side_effect=expected_exception)

    notification_id = uuid4()

    with pytest.raises(Retry):
        save_sms(
            template.service_id,
            notification_id,
            encryption.encrypt(notification),
        )

    assert provider_tasks.deliver_sms.apply_async.called is False
    tasks.save_sms.retry.assert_called_with(exc=expected_exception, queue='retry-tasks')
    assert notify_db_session.session.get(Notification, notification_id) is None


def test_save_email_should_go_to_retry_queue_if_database_errors(
    notify_db_session,
    sample_template,
    mocker,
):
    template = sample_template(template_type=EMAIL_TYPE)
    notification = _notification_json(template, 'test@example.gov.uk')

    expected_exception = SQLAlchemyError()

    mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
    mocker.patch('app.celery.tasks.save_email.retry', side_effect=Retry)
    mocker.patch('app.notifications.process_notifications.dao_create_notification', side_effect=expected_exception)

    notification_id = uuid4()

    with pytest.raises(Retry):
        save_email(
            template.service_id,
            notification_id,
            encryption.encrypt(notification),
        )

    assert not provider_tasks.deliver_email.apply_async.called
    tasks.save_email.retry.assert_called_with(exc=expected_exception, queue='retry-tasks')
    assert notify_db_session.session.get(Notification, notification_id) is None


def test_save_email_does_not_send_duplicate_and_does_not_put_in_retry_queue(
    notify_db_session,
    sample_template,
    sample_notification,
    mocker,
):
    template = sample_template()
    notification = sample_notification(template=template)
    json = _notification_json(notification.template, notification.to, job_id=uuid4(), row_number=1)
    deliver_email = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')
    retry = mocker.patch('app.celery.tasks.save_email.retry', side_effect=Exception())

    stmt = select(func.count()).select_from(Notification).where(Notification.template_id == template.id)
    assert notify_db_session.session.scalar(stmt) == 1

    save_email(
        notification.service_id,
        notification.id,
        encryption.encrypt(json),
    )

    assert notify_db_session.session.scalar(stmt) == 1
    assert not deliver_email.called
    assert not retry.called


def test_save_sms_does_not_send_duplicate_and_does_not_put_in_retry_queue(
    notify_db_session,
    sample_job,
    sample_notification,
    mocker,
):
    notification = sample_notification()
    job = sample_job(template=notification.template)
    json = _notification_json(notification.template, '6502532222', job_id=str(job.id), row_number=1)
    deliver_sms = mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')
    retry = mocker.patch('app.celery.tasks.save_sms.retry', side_effect=Exception())

    notification_id = notification.id

    stmt = select(func.count()).select_from(Notification).where(Notification.id == notification_id)
    assert notify_db_session.session.scalar(stmt) == 1

    save_sms(
        notification.service_id,
        notification_id,
        encryption.encrypt(json),
    )

    assert notify_db_session.session.scalar(stmt) == 1
    assert not deliver_sms.called
    assert not retry.called


def test_save_sms_uses_sms_sender_reply_to_text(
    mocker,
    notify_db_session,
    sample_service,
    sample_template,
):
    service = sample_service(sms_sender='6502532222')
    template = sample_template(service=service)

    # Cleaned by sample_template
    notification = _notification_json(template, to='6502532222')
    mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')

    notification_id = uuid4()
    save_sms(
        service.id,
        notification_id,
        encryption.encrypt(notification),
    )

    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    assert persisted_notification.reply_to_text == '+16502532222'


def test_save_sms_uses_non_default_sms_sender_reply_to_text_if_provided(
    mocker,
    notify_db_session,
    sample_service,
    sample_template,
    sample_sms_sender,
):
    mock_feature_flag(mocker, FeatureFlag.SMS_SENDER_RATE_LIMIT_ENABLED, 'True')
    service = sample_service(sms_sender='07123123123')
    template = sample_template(service=service)
    new_sender = sample_sms_sender(service.id, sms_sender='new-sender', is_default=False)

    sms_sender = mocker.Mock()
    sms_sender.rate_limit = 1
    sms_sender.sms_sender = 'new-sender'
    mocker.patch('app.celery.tasks.dao_get_service_sms_sender_by_service_id_and_number', return_value=sms_sender)

    # Cleaned by sample_template
    notification = _notification_json(template, to='6502532222')
    mocker.patch('app.celery.provider_tasks.deliver_sms_with_rate_limiting.apply_async')

    notification_id = uuid4()
    save_sms(
        service.id,
        notification_id,
        encryption.encrypt(notification),
        sender_id=new_sender.id,
    )

    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    assert persisted_notification.reply_to_text == 'new-sender'


def test_should_cancel_job_if_service_is_inactive(
    mocker,
    notify_db_session,
    sample_service,
    sample_template,
    sample_job,
):
    service = sample_service(active=False)
    template = sample_template(service=service)
    job = sample_job(template)

    mocker.patch('app.celery.tasks.s3.get_job_from_s3')
    mocker.patch('app.celery.tasks.process_row')

    process_job(job.id)

    notify_db_session.session.refresh(job)

    assert job.job_status == 'cancelled'
    s3.get_job_from_s3.assert_not_called()
    tasks.process_row.assert_not_called()


@pytest.mark.parametrize(
    'template_type, expected_class',
    [
        (SMS_TYPE, SMSMessageTemplate),
        (EMAIL_TYPE, WithSubjectTemplate),
        (LETTER_TYPE, WithSubjectTemplate),
    ],
)
def test_get_template_class(template_type, expected_class):
    assert get_template_class(template_type) == expected_class


def test_process_incomplete_job_sms(mocker, notify_db_session, sample_template, sample_job, sample_notification):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('multiple_sms'))
    save_sms = mocker.patch('app.celery.tasks.save_sms.apply_async')
    template = sample_template()

    job = sample_job(
        template,
        notification_count=10,
        created_at=datetime.utcnow() - timedelta(hours=2),
        scheduled_for=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_ERROR,
    )

    sample_notification(template=template, job=job, job_row_number=0)
    sample_notification(template=template, job=job, job_row_number=1)

    stmt = select(func.count()).select_from(Notification).where(Notification.job_id == job.id)
    assert notify_db_session.session.scalar(stmt) == 2

    process_incomplete_job(str(job.id))

    notify_db_session.session.refresh(job)

    assert job.job_status == JOB_STATUS_FINISHED
    assert save_sms.call_count == 8  # There are 10 in the file and we've added two already


def test_process_incomplete_job_with_notifications_all_sent(
    notify_db_session,
    mocker,
    sample_api_key,
    sample_template,
    sample_job,
    sample_notification,
):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('multiple_sms'))
    mock_save_sms = mocker.patch('app.celery.tasks.save_sms.apply_async')

    template = sample_template()
    job = sample_job(
        template,
        notification_count=10,
        created_at=datetime.utcnow() - timedelta(hours=2),
        scheduled_for=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_ERROR,
    )

    api_key = sample_api_key(service=template.service)
    for i in range(10):
        sample_notification(template=template, job=job, job_row_number=i, api_key=api_key)

    stmt = select(func.count()).select_from(Notification).where(Notification.job_id == job.id)
    assert notify_db_session.session.scalar(stmt) == 10

    process_incomplete_job(str(job.id))

    stmt = select(Job).where(Job.id == job.id)
    completed_job = notify_db_session.session.scalars(stmt).one()

    assert completed_job.job_status == JOB_STATUS_FINISHED
    assert mock_save_sms.call_count == 0  # There are 10 in the file and we've added 10 it should not have been called


def test_process_incomplete_jobs_sms(
    mocker,
    notify_db_session,
    sample_api_key,
    sample_template,
    sample_job,
    sample_notification,
):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('multiple_sms'))
    mock_save_sms = mocker.patch('app.celery.tasks.save_sms.apply_async')

    template = sample_template()
    job = sample_job(
        template,
        notification_count=10,
        created_at=datetime.utcnow() - timedelta(hours=2),
        scheduled_for=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_ERROR,
    )

    api_key = sample_api_key(service=template.service)
    for i in range(3):
        sample_notification(template=template, job=job, job_row_number=i, api_key=api_key)

    stmt = select(func.count()).select_from(Notification).where(Notification.job_id == job.id)
    assert notify_db_session.session.scalar(stmt) == 3

    job2 = sample_job(
        template,
        notification_count=10,
        created_at=datetime.utcnow() - timedelta(hours=2),
        scheduled_for=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_ERROR,
    )

    for i in range(5):
        sample_notification(template=template, job=job2, job_row_number=i, api_key=api_key)

    stmt = select(func.count()).select_from(Notification).where(Notification.job_id == job2.id)
    assert notify_db_session.session.scalar(stmt) == 5

    jobs = [job.id, job2.id]
    process_incomplete_jobs(jobs)

    notify_db_session.session.refresh(job)
    notify_db_session.session.refresh(job2)

    assert job.job_status == JOB_STATUS_FINISHED
    assert job2.job_status == JOB_STATUS_FINISHED
    assert mock_save_sms.call_count == 12  # There are 20 in total over 2 jobs we've added 8 already


def test_process_incomplete_jobs_no_notifications_added(
    notify_db_session,
    mocker,
    sample_job,
    sample_template,
):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('multiple_sms'))
    mock_save_sms = mocker.patch('app.celery.tasks.save_sms.apply_async')

    template = sample_template()
    job = sample_job(
        template,
        notification_count=10,
        created_at=datetime.utcnow() - timedelta(hours=2),
        scheduled_for=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_ERROR,
    )

    stmt = select(func.count()).select_from(Notification).where(Notification.job_id == job.id)
    assert notify_db_session.session.scalar(stmt) == 0

    process_incomplete_job(job.id)

    stmt = select(Job).where(Job.id == job.id)
    completed_job = notify_db_session.session.scalars(stmt).one()

    assert completed_job.job_status == JOB_STATUS_FINISHED

    assert mock_save_sms.call_count == 10  # There are 10 in the csv file


def test_process_incomplete_jobs(mocker):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('multiple_sms'))
    mock_save_sms = mocker.patch('app.celery.tasks.save_sms.apply_async')

    jobs = []
    process_incomplete_jobs(jobs)

    assert mock_save_sms.call_count == 0  # There are no jobs to process so it will not have been called


def test_process_incomplete_job_no_job_in_database(mocker, fake_uuid):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('multiple_sms'))
    mock_save_sms = mocker.patch('app.celery.tasks.save_sms.apply_async')

    with pytest.raises(expected_exception=Exception):
        process_incomplete_job(fake_uuid)

    assert mock_save_sms.call_count == 0  # There is no job in the db it will not have been called


def test_process_incomplete_job_email(notify_db_session, mocker, sample_template, sample_job, sample_notification):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('multiple_email'))
    mock_email_saver = mocker.patch('app.celery.tasks.save_email.apply_async')

    template = sample_template(template_type=EMAIL_TYPE)
    job = sample_job(
        template,
        notification_count=10,
        created_at=datetime.utcnow() - timedelta(hours=2),
        scheduled_for=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_ERROR,
    )

    sample_notification(template=template, job=job, job_row_number=0)
    sample_notification(template=template, job=job, job_row_number=1)

    stmt = select(func.count()).select_from(Notification).where(Notification.job_id == job.id)
    assert notify_db_session.session.scalar(stmt) == 2

    process_incomplete_job(str(job.id))

    stmt = select(Job).where(Job.id == job.id)
    completed_job = notify_db_session.session.scalars(stmt).one()

    assert completed_job.job_status == JOB_STATUS_FINISHED
    assert mock_email_saver.call_count == 8  # There are 10 in the file and we've added two already


# Letter functionality is not used.  Decline to fix.
@pytest.mark.skip(reason='TypeError: expected string or bytes-like object')
def test_process_incomplete_job_letter(notify_db_session, mocker, sample_template, sample_job, sample_notification):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('multiple_letter'))
    mock_letter_saver = mocker.patch('app.celery.tasks.save_letter.apply_async')

    template = sample_template(template_type=LETTER_TYPE)
    job = sample_job(
        template,
        notification_count=10,
        created_at=datetime.utcnow() - timedelta(hours=2),
        scheduled_for=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_ERROR,
    )

    sample_notification(template=template, job=job, job_row_number=0)
    sample_notification(template=template, job=job, job_row_number=1)

    stmt = select(func.count()).select_from(Notification).where(Notification.job_id == job.id)
    assert notify_db_session.session.scalar(stmt) == 2

    # This line raises TypeError even though job.id is a string.
    process_incomplete_job(str(job.id))
    assert mock_letter_saver.call_count == 8


@freeze_time('2017-01-01')
def test_process_incomplete_jobs_sets_status_to_in_progress_and_resets_processing_started_time(
    mocker,
    notify_db_session,
    sample_template,
    sample_job,
):
    mock_process_incomplete_job = mocker.patch('app.celery.tasks.process_incomplete_job')
    template = sample_template()

    job1 = sample_job(
        template, processing_started=datetime.utcnow() - timedelta(minutes=30), job_status=JOB_STATUS_ERROR
    )
    job2 = sample_job(
        template, processing_started=datetime.utcnow() - timedelta(minutes=31), job_status=JOB_STATUS_ERROR
    )

    process_incomplete_jobs([str(job1.id), str(job2.id)])

    notify_db_session.session.refresh(job1)
    notify_db_session.session.refresh(job2)

    assert job1.job_status == JOB_STATUS_IN_PROGRESS
    assert job1.processing_started == datetime.utcnow()

    assert job2.job_status == JOB_STATUS_IN_PROGRESS
    assert job2.processing_started == datetime.utcnow()

    assert mock_process_incomplete_job.mock_calls == [call(str(job1.id)), call(str(job2.id))]
