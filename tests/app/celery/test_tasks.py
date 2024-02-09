import pytest
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
    process_returned_letters_list,
)
from app.config import QueueNames
from app.dao import service_email_reply_to_dao
from app.feature_flags import FeatureFlag
from app.models import (
    Job,
    Notification,
    NotificationHistory,
    EMAIL_TYPE,
    KEY_TYPE_NORMAL,
    JOB_STATUS_FINISHED,
    JOB_STATUS_ERROR,
    JOB_STATUS_IN_PROGRESS,
    LETTER_TYPE,
    ServiceSmsSender,
    SMS_TYPE,
)
from celery.exceptions import Retry
from datetime import datetime, timedelta
from freezegun import freeze_time
from notifications_utils.columns import Row
from notifications_utils.template import SMSMessageTemplate, WithSubjectTemplate
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from tests.app import load_example_csv
from tests.app.db import (
    create_letter_contact,
    create_service,
    create_template,
    create_notification_history,
)
from tests.app.factories.feature_flag import mock_feature_flag
from tests.conftest import set_config_values
from unittest.mock import Mock, call
from uuid import uuid4


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


def test_should_process_sms_job(mocker, sample_template, sample_job, notify_db_session):
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
        (str(job.service_id), 'uuid', 'something_encrypted'), {}, queue='database-tasks'
    )

    # Retrieve job from db
    notify_db_session.session.refresh(job)
    assert job.job_status == 'finished'


def test_should_process_sms_job_with_sender_id(mocker, fake_uuid, sample_template, sample_job):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv(SMS_TYPE))
    mocker.patch('app.celery.tasks.save_sms.apply_async')
    mocker.patch('app.encryption.encrypt', return_value='something_encrypted')
    mocker.patch('app.celery.tasks.create_uuid', return_value='uuid')

    template = sample_template()
    job = sample_job(template=template)
    process_job(job.id, sender_id=fake_uuid)

    tasks.save_sms.apply_async.assert_called_once_with(
        (str(job.service_id), 'uuid', 'something_encrypted'), {'sender_id': fake_uuid}, queue='database-tasks'
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
    mocker, sample_service, sample_template, sample_job, sample_notification, notify_db_session
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
    template_type, mocker, notify_db_session, sample_service, sample_template, sample_job, sample_notification
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


def test_should_not_process_job_if_already_pending(sample_template, sample_job, mocker):
    template = sample_template()
    job = sample_job(template, job_status='scheduled')

    mocker.patch('app.celery.tasks.s3.get_job_from_s3')
    mocker.patch('app.celery.tasks.process_row')

    process_job(job.id)

    assert s3.get_job_from_s3.called is False
    assert tasks.process_row.called is False


def test_should_process_email_job_if_exactly_on_send_limits(
    mocker, notify_db_session, sample_service, sample_template, sample_job
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
        queue='database-tasks',
    )


def test_should_not_create_save_task_for_empty_file(mocker, notify_db_session, sample_template, sample_job):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('empty'))
    mocker.patch('app.celery.tasks.save_sms.apply_async')

    template = sample_template()
    job = sample_job(template)
    process_job(job.id)

    s3.get_job_from_s3.assert_called_once_with(str(job.service.id), str(job.id))

    notify_db_session.session.refresh(job)

    assert job.job_status == 'finished'
    assert tasks.save_sms.apply_async.called is False


def test_should_process_email_job(mocker, notify_db_session, sample_template, sample_job):
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
        queue='database-tasks',
    )

    notify_db_session.session.refresh(job)

    assert job.job_status == 'finished'


def test_should_process_email_job_with_sender_id(mocker, fake_uuid, sample_template, sample_job):
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
        queue='database-tasks',
    )


@pytest.mark.skip(reason='Letter functionality is not used and will be removed.')
@freeze_time('2016-01-01 11:09:00.061258')
def test_should_process_letter_job(sample_letter_job, mocker):
    csv = """address_line_1,address_line_2,address_line_3,address_line_4,postcode,name
    A1,A2,A3,A4,A_POST,Alice
    """
    s3_mock = mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=csv)
    process_row_mock = mocker.patch('app.celery.tasks.process_row')
    mocker.patch('app.celery.tasks.create_uuid', return_value='uuid')

    process_job(sample_letter_job.id)

    s3_mock.assert_called_once_with(str(sample_letter_job.service.id), str(sample_letter_job.id))

    row_call = process_row_mock.mock_calls[0][1]
    assert row_call[0].index == 0
    assert row_call[0].recipient == ['A1', 'A2', 'A3', 'A4', None, None, 'A_POST']
    assert row_call[0].personalisation == {
        'addressline1': 'A1',
        'addressline2': 'A2',
        'addressline3': 'A3',
        'addressline4': 'A4',
        'postcode': 'A_POST',
    }
    assert row_call[2] == sample_letter_job
    assert row_call[3] == sample_letter_job.service

    assert process_row_mock.call_count == 1

    assert sample_letter_job.job_status == 'finished'


# -------------- process_row tests -------------- #


def test_should_process_all_sms_job(mocker, notify_db_session, sample_template, sample_job):
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
        (SMS_TYPE, False, 'save_sms', 'database-tasks'),
        (SMS_TYPE, True, 'save_sms', 'research-mode-tasks'),
        (EMAIL_TYPE, False, 'save_email', 'database-tasks'),
        (EMAIL_TYPE, True, 'save_email', 'research-mode-tasks'),
        (LETTER_TYPE, False, 'save_letter', 'database-tasks'),
        (LETTER_TYPE, True, 'save_letter', 'research-mode-tasks'),
    ],
)
def test_process_row_sends_letter_task(template_type, research_mode, expected_function, expected_queue, mocker):
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
        queue='database-tasks',
    )


def test_should_send_template_to_correct_sms_task_and_persist(
    notify_db_session, sample_template_with_placeholders, mocker
):
    notification = _notification_json(
        sample_template_with_placeholders, to='+1 650 253 2222', personalisation={'name': 'Jo'}
    )

    mocked_deliver_sms = mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')

    notification_id = uuid4()

    save_sms(
        sample_template_with_placeholders.service_id,
        notification_id,
        encryption.encrypt(notification),
    )

    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    try:
        assert persisted_notification.to == '+1 650 253 2222'
        assert persisted_notification.template_id == sample_template_with_placeholders.id
        assert persisted_notification.template_version == sample_template_with_placeholders.version
        assert persisted_notification.status == 'created'
        assert persisted_notification.created_at <= datetime.utcnow()
        assert not persisted_notification.sent_at
        assert not persisted_notification.sent_by
        assert not persisted_notification.job_id
        assert persisted_notification.personalisation == {'name': 'Jo'}
        assert persisted_notification._personalisation == encryption.encrypt({'name': 'Jo'})
        assert persisted_notification.notification_type == SMS_TYPE
        mocked_deliver_sms.assert_called_once_with([str(persisted_notification.id)], queue='send-sms-tasks')
    finally:
        notify_db_session.session.delete(persisted_notification)
        notify_db_session.session.commit()


def test_should_put_save_sms_task_in_research_mode_queue_if_research_mode_service(
    notify_db_session, mocker, sample_service, sample_template
):
    service = sample_service(research_mode=True)
    template = sample_template(service=service)
    notification = _notification_json(template, to='+1 650 253 2222')
    mocked_deliver_sms = mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')
    notification_id = uuid4()

    save_sms(
        template.service_id,
        notification_id,
        encryption.encrypt(notification),
    )
    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    try:
        provider_tasks.deliver_sms.apply_async.assert_called_once_with(
            [str(persisted_notification.id)], queue='research-mode-tasks'
        )
        assert mocked_deliver_sms.called
    finally:
        # Teardown
        notify_db_session.session.delete(persisted_notification)
        notify_db_session.session.commit()


def test_should_save_sms_if_restricted_service_and_valid_number(
    notify_db_session, mocker, sample_user, sample_service, sample_template
):
    user = sample_user(mobile_number='6502532222')
    service = sample_service(user=user, restricted=True)
    template = sample_template(service=service)
    notification = _notification_json(template, '+16502532222')

    mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')

    notification_id = uuid4()
    encrypt_notification = encryption.encrypt(notification)
    save_sms(
        service.id,
        notification_id,
        encrypt_notification,
    )

    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    try:
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
            [str(persisted_notification.id)], queue='send-sms-tasks'
        )
    finally:
        # Teardown
        notify_db_session.session.delete(persisted_notification)
        notify_db_session.session.commit()


def test_save_sms_should_call_deliver_sms_with_rate_limiting_if_sender_id_provided(
    notify_db_session, mocker, sample_user, sample_service, sample_template
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
    notification = _notification_json(template, '+16502532222')
    sender_id = uuid4()

    deliver_sms = mocker.patch('app.celery.provider_tasks.deliver_sms_with_rate_limiting.apply_async')

    notification_id = uuid4()
    encrypt_notification = encryption.encrypt(notification)

    save_sms(service.id, notification_id, encrypt_notification, sender_id)
    notification2 = notify_db_session.session.get(Notification, notification_id)
    assert notification2 is not None

    try:
        deliver_sms.assert_called_once_with([str(notification_id)], queue='send-sms-tasks')
    finally:
        # Teardown
        notify_db_session.session.delete(notification2)
        notify_db_session.session.commit()


def test_save_email_should_save_default_email_reply_to_text_on_notification(
    mocker,
    notify_db_session,
    sample_service,
    sample_template,
    sample_service_email_reply_to,
):
    service = sample_service()
    template = sample_template(service=service, template_type=EMAIL_TYPE, subject='Hello')
    reply_to_address = f'{uuid4()}@test.va.gov'

    sample_service_email_reply_to(service=service, email_address=reply_to_address, is_default=True)

    notification = _notification_json(template, to='test@example.com')
    mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    notification_id = uuid4()
    save_email(
        service.id,
        notification_id,
        encryption.encrypt(notification),
    )

    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    try:
        assert persisted_notification.reply_to_text == reply_to_address
    finally:
        # Teardown
        notify_db_session.session.delete(persisted_notification)
        notify_db_session.session.commit()


def test_save_sms_should_save_default_sms_sender_notification_reply_to_text_on(
    notify_db_session, mocker, sample_service, sample_template
):
    service = sample_service()
    template = sample_template(service=service)

    # sample_service also creates and persists an instance of ServiceSmsSender.
    query = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
    sms_sender = notify_db_session.session.scalar(query)
    sms_sender.sms_sender = '12345'
    sms_sender.is_default = True

    notify_db_session.session.add(sms_sender)
    notify_db_session.session.commit()

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

    try:
        assert persisted_notification.reply_to_text == '12345'
    finally:
        # Teardown
        notify_db_session.session.delete(persisted_notification)
        notify_db_session.session.commit()


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
    mocker, notify_db_session, sample_service, sample_template
):
    service = sample_service(research_mode=True)
    template = sample_template(service=service, template_type=EMAIL_TYPE)
    notification = _notification_json(template, to='test@test.com')

    mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    notification_id = uuid4()

    save_email(
        template.service_id,
        notification_id,
        encryption.encrypt(notification),
    )

    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    try:
        provider_tasks.deliver_email.apply_async.assert_called_once_with(
            [str(persisted_notification.id)], queue='research-mode-tasks'
        )
    finally:
        # Teardown
        notify_db_session.session.delete(persisted_notification)
        notify_db_session.session.commit()


def test_should_save_sms_template_to_and_persist_with_job_id(notify_db_session, sample_template, sample_job, mocker):
    template = sample_template()
    assert template.template_type == SMS_TYPE
    job = sample_job(template)
    notification = _notification_json(job.template, to='+1 650 253 2222', job_id=job.id, row_number=2)
    mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')

    notification_id = uuid4()
    now = datetime.utcnow()
    save_sms(
        job.service.id,
        notification_id,
        encryption.encrypt(notification),
    )
    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    try:
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
            [str(persisted_notification.id)], queue='send-sms-tasks'
        )
    finally:
        # Teardown
        notify_db_session.session.delete(persisted_notification)
        notify_db_session.session.commit()


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


def test_should_use_email_template_and_persist(notify_db_session, sample_email_template_with_placeholders, mocker):
    mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    now = datetime(2016, 1, 1, 11, 9, 0)
    notification_id = uuid4()

    with freeze_time('2016-01-01 12:00:00.000000'):
        notification = _notification_json(
            sample_email_template_with_placeholders, 'my_email@my_email.com', {'name': 'Jo'}, row_number=1
        )

    with freeze_time('2016-01-01 11:10:00.00000'):
        save_email(
            sample_email_template_with_placeholders.service_id,
            notification_id,
            encryption.encrypt(notification),
        )

    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    try:
        assert persisted_notification.to == 'my_email@my_email.com'
        assert persisted_notification.template_id == sample_email_template_with_placeholders.id
        assert persisted_notification.template_version == sample_email_template_with_placeholders.version
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
            [str(persisted_notification.id)], queue='send-email-tasks'
        )
    finally:
        # Teardown
        notify_db_session.session.delete(persisted_notification)
        notify_db_session.session.commit()


def test_save_email_should_use_template_version_from_job_not_latest(notify_db_session, sample_template, mocker):
    template = sample_template(template_type=EMAIL_TYPE)
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

    try:
        assert persisted_notification.to == 'my_email@my_email.com'
        assert persisted_notification.template_id == template.id
        assert persisted_notification.template_version == version_on_notification
        assert persisted_notification.created_at >= now
        assert not persisted_notification.sent_at
        assert persisted_notification.status == 'created'
        assert not persisted_notification.sent_by
        assert persisted_notification.notification_type == EMAIL_TYPE
        provider_tasks.deliver_email.apply_async.assert_called_once_with(
            [str(persisted_notification.id)], queue='send-email-tasks'
        )
    finally:
        # Teardown
        notify_db_session.session.delete(persisted_notification)
        notify_db_session.session.commit()


def test_should_use_email_template_subject_placeholders(
    notify_db_session, sample_email_template_with_placeholders, mocker
):
    notification = _notification_json(sample_email_template_with_placeholders, 'my_email@my_email.com', {'name': 'Jo'})
    mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    notification_id = uuid4()
    now = datetime.utcnow()
    save_email(
        sample_email_template_with_placeholders.service_id,
        notification_id,
        encryption.encrypt(notification),
    )
    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    try:
        assert persisted_notification.to == 'my_email@my_email.com'
        assert persisted_notification.template_id == sample_email_template_with_placeholders.id
        assert persisted_notification.status == 'created'
        assert persisted_notification.created_at >= now
        assert not persisted_notification.sent_by
        assert persisted_notification.personalisation == {'name': 'Jo'}
        assert not persisted_notification.reference
        assert persisted_notification.notification_type == EMAIL_TYPE
        provider_tasks.deliver_email.apply_async.assert_called_once_with(
            [str(persisted_notification.id)], queue='send-email-tasks'
        )
    finally:
        # Teardown
        notify_db_session.session.delete(persisted_notification)
        notify_db_session.session.commit()


def test_save_email_uses_the_reply_to_text_when_provided(notify_db_session, mocker, sample_service, sample_template):
    service = sample_service()
    template = sample_template(template_type=EMAIL_TYPE, service=service)
    notification = _notification_json(template, 'my_email@my_email.com')
    mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    notification_id = uuid4()
    service_email_reply_to = service_email_reply_to_dao.add_reply_to_email_address_for_service(
        service.id, 'default@example.com', True
    )
    other_email_reply_to = service_email_reply_to_dao.add_reply_to_email_address_for_service(
        service.id, 'other@example.com', False
    )

    save_email(
        template.service_id,
        notification_id,
        encryption.encrypt(notification),
        sender_id=other_email_reply_to.id,
    )
    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    try:
        assert persisted_notification.notification_type == EMAIL_TYPE
        assert persisted_notification.reply_to_text == 'other@example.com'
    finally:
        # Teardown
        notify_db_session.session.delete(other_email_reply_to)
        notify_db_session.session.delete(service_email_reply_to)
        notify_db_session.session.delete(persisted_notification)
        notify_db_session.session.commit()


def test_save_email_uses_the_default_reply_to_text_if_sender_id_is_none(
    notify_db_session, mocker, sample_service, sample_template
):
    service = sample_service()
    template = sample_template(template_type=EMAIL_TYPE, service=service)
    notification = _notification_json(template, 'my_email@my_email.com')
    mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    notification_id = uuid4()
    service_email_reply_to = service_email_reply_to_dao.add_reply_to_email_address_for_service(
        service.id, 'default@example.com', True
    )

    save_email(
        template.service_id,
        notification_id,
        encryption.encrypt(notification),
        sender_id=None,
    )
    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    try:
        assert persisted_notification.notification_type == EMAIL_TYPE
        assert persisted_notification.reply_to_text == 'default@example.com'
    finally:
        # Teardown
        notify_db_session.session.delete(service_email_reply_to)
        notify_db_session.session.delete(persisted_notification)
        notify_db_session.session.commit()


def test_should_use_email_template_and_persist_without_personalisation(notify_db_session, sample_template, mocker):
    template = sample_template(template_type=EMAIL_TYPE)
    assert template.template_type == EMAIL_TYPE
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

    try:
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
            [str(persisted_notification.id)], queue='send-email-tasks'
        )
    finally:
        # Teardown
        notify_db_session.session.delete(persisted_notification)
        notify_db_session.session.commit()


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


@pytest.mark.skip(reason='Letter functionality is not used and will be removed.')
def test_save_letter_saves_letter_to_database(mocker, notify_db_session, sample_job):
    service = create_service()
    contact_block = create_letter_contact(service=service, contact_block='Address contact', is_default=True)
    template = create_template(service=service, template_type=LETTER_TYPE, reply_to=contact_block.id)
    job = sample_job(template)

    mocker.patch('app.celery.tasks.create_random_identifier', return_value='this-is-random-in-real-life')
    mocker.patch('app.celery.tasks.letters_pdf_tasks.create_letters_pdf.apply_async')

    personalisation = {
        'addressline1': 'Foo',
        'addressline2': 'Bar',
        'addressline3': 'Baz',
        'addressline4': 'Wibble',
        'addressline5': 'Wobble',
        'addressline6': 'Wubble',
        'postcode': 'Flob',
    }
    notification_json = _notification_json(
        template=job.template, to='Foo', personalisation=personalisation, job_id=job.id, row_number=1
    )
    notification_id = uuid4()
    created_at = datetime.utcnow()

    save_letter(
        job.service_id,
        notification_id,
        encryption.encrypt(notification_json),
    )

    notification_db = notify_db_session.session.get(Notification, notification_id)

    assert notification_db.id == notification_id
    assert notification_db.to == 'Foo'
    assert notification_db.job_id == job.id
    assert notification_db.template_id == job.template.id
    assert notification_db.template_version == job.template.version
    assert notification_db.status == 'created'
    assert notification_db.created_at >= created_at
    assert notification_db.notification_type == 'letter'
    assert notification_db.sent_at is None
    assert notification_db.sent_by is None
    assert notification_db.personalisation == personalisation
    assert notification_db.reference == 'this-is-random-in-real-life'
    assert notification_db.reply_to_text == contact_block.contact_block


@pytest.mark.skip(reason='Letter functionality is not used and will be removed.')
@pytest.mark.parametrize('postage', ['first', 'second'])
def test_save_letter_saves_letter_to_database_with_correct_postage(mocker, notify_db_session, postage, sample_job):
    service = create_service(service_permissions=[LETTER_TYPE])
    template = create_template(service=service, template_type=LETTER_TYPE, postage=postage)
    letter_job = sample_job(template)

    mocker.patch('app.celery.tasks.letters_pdf_tasks.create_letters_pdf.apply_async')
    notification_json = _notification_json(
        template=letter_job.template,
        to='Foo',
        personalisation={'addressline1': 'Foo', 'addressline2': 'Bar', 'postcode': 'Flob'},
        job_id=letter_job.id,
        row_number=1,
    )
    notification_id = uuid4()
    save_letter(
        letter_job.service_id,
        notification_id,
        encryption.encrypt(notification_json),
    )

    notification_db = notify_db_session.session.get(Notification, notification_id)
    assert notification_db.id == notification_id
    assert notification_db.postage == postage


@pytest.mark.skip(reason='Letter functionality is not used and will be removed.')
def test_save_letter_saves_letter_to_database_right_reply_to(mocker, notify_db_session, sample_job):
    service = create_service()
    create_letter_contact(service=service, contact_block='Address contact', is_default=True)
    template = create_template(service=service, template_type=LETTER_TYPE, reply_to=None)
    job = sample_job(template)

    mocker.patch('app.celery.tasks.create_random_identifier', return_value='this-is-random-in-real-life')
    mocker.patch('app.celery.tasks.letters_pdf_tasks.create_letters_pdf.apply_async')

    personalisation = {
        'addressline1': 'Foo',
        'addressline2': 'Bar',
        'addressline3': 'Baz',
        'addressline4': 'Wibble',
        'addressline5': 'Wobble',
        'addressline6': 'Wubble',
        'postcode': 'Flob',
    }
    notification_json = _notification_json(
        template=job.template, to='Foo', personalisation=personalisation, job_id=job.id, row_number=1
    )
    notification_id = uuid4()
    created_at = datetime.utcnow()

    save_letter(
        job.service_id,
        notification_id,
        encryption.encrypt(notification_json),
    )

    notification_db = notify_db_session.session.get(Notification, notification_id)
    assert notification_db.id == notification_id
    assert notification_db.to == 'Foo'
    assert notification_db.job_id == job.id
    assert notification_db.template_id == job.template.id
    assert notification_db.template_version == job.template.version
    assert notification_db.status == 'created'
    assert notification_db.created_at >= created_at
    assert notification_db.notification_type == 'letter'
    assert notification_db.sent_at is None
    assert notification_db.sent_by is None
    assert notification_db.personalisation == personalisation
    assert notification_db.reference == 'this-is-random-in-real-life'
    assert not notification_db.reply_to_text


@pytest.mark.skip(reason='Letter functionality is not used and will be removed.')
def test_save_letter_uses_template_reply_to_text(mocker, notify_db_session, sample_job):
    service = create_service()
    create_letter_contact(service=service, contact_block='Address contact', is_default=True)
    template_contact = create_letter_contact(
        service=service, contact_block='Template address contact', is_default=False
    )
    template = create_template(service=service, template_type=LETTER_TYPE, reply_to=template_contact.id)

    job = sample_job(template)

    mocker.patch('app.celery.tasks.create_random_identifier', return_value='this-is-random-in-real-life')
    mocker.patch('app.celery.tasks.letters_pdf_tasks.create_letters_pdf.apply_async')

    personalisation = {
        'addressline1': 'Foo',
        'addressline2': 'Bar',
        'postcode': 'Flob',
    }
    notification_json = _notification_json(
        template=job.template, to='Foo', personalisation=personalisation, job_id=job.id, row_number=1
    )

    notification_id = uuid4()

    save_letter(
        job.service_id,
        notification_id,
        encryption.encrypt(notification_json),
    )

    notification_db = notify_db_session.session.get(Notification, notification_id)
    assert notification_db.reply_to_text == 'Template address contact'


def test_save_sms_uses_sms_sender_reply_to_text(mocker, notify_db_session, sample_service, sample_template):
    service = sample_service(sms_sender='6502532222')
    template = sample_template(service=service)

    notification = _notification_json(template, to='6502532222')
    mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')

    notification_id = uuid4()
    save_sms(
        service.id,
        notification_id,
        encryption.encrypt(notification),
    )

    persisted_notification = notify_db_session.session.get(Notification, notification_id)

    try:
        assert persisted_notification.reply_to_text == '+16502532222'
    finally:
        # Teardown
        notify_db_session.session.delete(persisted_notification)
        notify_db_session.session.commit()


def test_save_sms_uses_non_default_sms_sender_reply_to_text_if_provided(
    mocker, notify_db_session, sample_service, sample_template, sample_sms_sender_v2
):
    mock_feature_flag(mocker, FeatureFlag.SMS_SENDER_RATE_LIMIT_ENABLED, 'True')
    service = sample_service(sms_sender='07123123123')
    template = sample_template(service=service)
    # new_sender = service_sms_sender_dao.dao_add_sms_sender_for_service(service.id, 'new-sender', False)
    new_sender = sample_sms_sender_v2(service.id, sms_sender='new-sender', is_default=False)
    sms_sender = mocker.Mock()
    sms_sender.rate_limit = 1
    sms_sender.sms_sender = 'new-sender'
    mocker.patch('app.celery.tasks.dao_get_service_sms_sender_by_service_id_and_number', return_value=sms_sender)

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

    try:
        assert persisted_notification.reply_to_text == 'new-sender'
    finally:
        # Teardown
        notify_db_session.session.delete(persisted_notification)
        notify_db_session.session.commit()


@pytest.mark.skip(reason='Letter functionality is not used and will be removed.')
@pytest.mark.parametrize('env', ['staging', 'live'])
def test_save_letter_sets_delivered_letters_as_pdf_permission_in_research_mode_in_staging_live(
    notify_api, mocker, notify_db_session, sample_letter_job, env
):
    sample_letter_job.service.research_mode = True
    sample_reference = 'this-is-random-in-real-life'
    mock_create_fake_letter_response_file = mocker.patch(
        'app.celery.research_mode_tasks.create_fake_letter_response_file.apply_async'
    )
    mocker.patch('app.celery.tasks.create_random_identifier', return_value=sample_reference)

    personalisation = {
        'addressline1': 'Foo',
        'addressline2': 'Bar',
        'postcode': 'Flob',
    }
    notification_json = _notification_json(
        template=sample_letter_job.template,
        to='Foo',
        personalisation=personalisation,
        job_id=sample_letter_job.id,
        row_number=1,
    )
    notification_id = uuid4()

    with set_config_values(notify_api, {'NOTIFY_ENVIRONMENT': env}):
        save_letter(
            sample_letter_job.service_id,
            notification_id,
            encryption.encrypt(notification_json),
        )

    notification = Notification.query.filter(Notification.id == notification_id).one()
    assert notification.status == 'delivered'
    assert not mock_create_fake_letter_response_file.called


@pytest.mark.skip(reason='Letter functionality is not used and will be removed.')
@pytest.mark.parametrize('env', ['development', 'preview'])
def test_save_letter_calls_create_fake_response_for_letters_in_research_mode_on_development_preview(
    notify_api, mocker, notify_db_session, sample_letter_job, env
):
    sample_letter_job.service.research_mode = True
    sample_reference = 'this-is-random-in-real-life'
    mock_create_fake_letter_response_file = mocker.patch(
        'app.celery.research_mode_tasks.create_fake_letter_response_file.apply_async'
    )
    mocker.patch('app.celery.tasks.create_random_identifier', return_value=sample_reference)

    personalisation = {
        'addressline1': 'Foo',
        'addressline2': 'Bar',
        'postcode': 'Flob',
    }
    notification_json = _notification_json(
        template=sample_letter_job.template,
        to='Foo',
        personalisation=personalisation,
        job_id=sample_letter_job.id,
        row_number=1,
    )
    notification_id = uuid4()

    with set_config_values(notify_api, {'NOTIFY_ENVIRONMENT': env}):
        save_letter(
            sample_letter_job.service_id,
            notification_id,
            encryption.encrypt(notification_json),
        )

    mock_create_fake_letter_response_file.assert_called_once_with((sample_reference,), queue=QueueNames.RESEARCH_MODE)


@pytest.mark.skip(reason='Letter functionality is not used and will be removed.')
def test_save_letter_calls_create_letters_pdf_task_not_in_research(mocker, notify_db_session, sample_letter_job):
    mock_create_letters_pdf = mocker.patch('app.celery.letters_pdf_tasks.create_letters_pdf.apply_async')

    personalisation = {
        'addressline1': 'Foo',
        'addressline2': 'Bar',
        'postcode': 'Flob',
    }
    notification_json = _notification_json(
        template=sample_letter_job.template,
        to='Foo',
        personalisation=personalisation,
        job_id=sample_letter_job.id,
        row_number=1,
    )
    notification_id = uuid4()

    save_letter(
        sample_letter_job.service_id,
        notification_id,
        encryption.encrypt(notification_json),
    )

    assert mock_create_letters_pdf.called
    mock_create_letters_pdf.assert_called_once_with([str(notification_id)], queue=QueueNames.CREATE_LETTERS_PDF)


def test_should_cancel_job_if_service_is_inactive(
    mocker, notify_db_session, sample_service, sample_template, sample_job
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

    assert Notification.query.filter(Notification.job_id == job.id).count() == 2

    process_incomplete_job(str(job.id))

    notify_db_session.session.refresh(job)

    assert job.job_status == JOB_STATUS_FINISHED
    assert save_sms.call_count == 8  # There are 10 in the file and we've added two already


def test_process_incomplete_job_with_notifications_all_sent(mocker, sample_template, sample_job, sample_notification):
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

    sample_notification(template=template, job=job, job_row_number=0)
    sample_notification(template=template, job=job, job_row_number=1)
    sample_notification(template=template, job=job, job_row_number=2)
    sample_notification(template=template, job=job, job_row_number=3)
    sample_notification(template=template, job=job, job_row_number=4)
    sample_notification(template=template, job=job, job_row_number=5)
    sample_notification(template=template, job=job, job_row_number=6)
    sample_notification(template=template, job=job, job_row_number=7)
    sample_notification(template=template, job=job, job_row_number=8)
    sample_notification(template=template, job=job, job_row_number=9)
    assert Notification.query.filter(Notification.job_id == job.id).count() == 10

    process_incomplete_job(str(job.id))
    completed_job = Job.query.filter(Job.id == job.id).one()
    assert completed_job.job_status == JOB_STATUS_FINISHED
    assert mock_save_sms.call_count == 0  # There are 10 in the file and we've added 10 it should not have been called


def test_process_incomplete_jobs_sms(mocker, notify_db_session, sample_template, sample_job, sample_notification):
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

    sample_notification(template=template, job=job, job_row_number=0)
    sample_notification(template=template, job=job, job_row_number=1)
    sample_notification(template=template, job=job, job_row_number=2)
    assert Notification.query.filter(Notification.job_id == job.id).count() == 3

    job2 = sample_job(
        template,
        notification_count=10,
        created_at=datetime.utcnow() - timedelta(hours=2),
        scheduled_for=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_ERROR,
    )

    sample_notification(template=template, job=job2, job_row_number=0)
    sample_notification(template=template, job=job2, job_row_number=1)
    sample_notification(template=template, job=job2, job_row_number=2)
    sample_notification(template=template, job=job2, job_row_number=3)
    sample_notification(template=template, job=job2, job_row_number=4)
    assert Notification.query.filter(Notification.job_id == job2.id).count() == 5

    jobs = [job.id, job2.id]
    process_incomplete_jobs(jobs)

    notify_db_session.session.refresh(job)
    notify_db_session.session.refresh(job2)

    assert job.job_status == JOB_STATUS_FINISHED
    assert job2.job_status == JOB_STATUS_FINISHED
    assert mock_save_sms.call_count == 12  # There are 20 in total over 2 jobs we've added 8 already


def test_process_incomplete_jobs_no_notifications_added(mocker, sample_template, sample_job):
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

    assert Notification.query.filter(Notification.job_id == job.id).count() == 0

    process_incomplete_job(job.id)

    completed_job = Job.query.filter(Job.id == job.id).one()

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


def test_process_incomplete_job_email(mocker, sample_template, sample_job, sample_notification):
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
    assert Notification.query.filter(Notification.job_id == job.id).count() == 2

    process_incomplete_job(str(job.id))
    completed_job = Job.query.filter(Job.id == job.id).one()
    assert completed_job.job_status == JOB_STATUS_FINISHED
    assert mock_email_saver.call_count == 8  # There are 10 in the file and we've added two already


# Letter functionality is not used.  Decline to fix.
@pytest.mark.xfail(reason='TypeError: expected string or bytes-like object', run=False)
def test_process_incomplete_job_letter(mocker, sample_template, sample_job, sample_notification):
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
    assert Notification.query.filter(Notification.job_id == job.id).count() == 2

    # This line raises TypeError even though job.id is a string.
    process_incomplete_job(str(job.id))
    assert mock_letter_saver.call_count == 8


@freeze_time('2017-01-01')
def test_process_incomplete_jobs_sets_status_to_in_progress_and_resets_processing_started_time(
    mocker, notify_db_session, sample_template, sample_job
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


@pytest.mark.skip(reason='Letter functionality is not used and will be removed.')
def test_process_returned_letters_list(sample_template, sample_notification):
    template = sample_template(template_type=LETTER_TYPE)
    sample_notification(template=template, reference='ref1')
    sample_notification(template=template, reference='ref2')

    process_returned_letters_list(['ref1', 'ref2', 'unknown-ref'])

    notifications = Notification.query.all()

    assert [n.status for n in notifications] == ['returned-letter', 'returned-letter']
    assert all(n.updated_at for n in notifications)


@pytest.mark.skip(reason='Letter functionality is not used and will be removed.')
def test_process_returned_letters_list_updates_history_if_notification_is_already_purged(sample_template):
    template = sample_template(template_type=LETTER_TYPE)
    create_notification_history(template=template, reference='ref1')
    create_notification_history(template=template, reference='ref2')

    process_returned_letters_list(['ref1', 'ref2', 'unknown-ref'])

    notifications = NotificationHistory.query.all()

    assert [n.status for n in notifications] == ['returned-letter', 'returned-letter']
    assert all(n.updated_at for n in notifications)
