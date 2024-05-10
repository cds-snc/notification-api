from datetime import datetime, timedelta
from decimal import Decimal, getcontext
from unittest.mock import ANY, call, MagicMock, patch
from uuid import UUID

import pytest
from freezegun import freeze_time
import boto3
from moto import mock_dynamodb

from app.celery import scheduled_tasks
from app.celery.scheduled_tasks import (
    send_scheduled_comp_and_pen_sms,
    _get_dynamodb_comp_pen_messages,
    _update_dynamo_item_is_processed,
    check_job_status,
    delete_invitations,
    delete_verify_codes,
    run_scheduled_jobs,
    send_scheduled_notifications,
    replay_created_notifications,
    check_precompiled_letter_state,
)
from app.config import QueueNames, TaskNames
from app.dao.jobs_dao import dao_get_job_by_id
from app.dao.notifications_dao import dao_get_scheduled_notifications
from app.models import (
    EMAIL_TYPE,
    JOB_STATUS_ERROR,
    JOB_STATUS_FINISHED,
    JOB_STATUS_IN_PROGRESS,
    JOB_STATUS_PENDING,
    JOB_STATUS_SCHEDULED,
    LETTER_TYPE,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PENDING_VIRUS_CHECK,
    SMS_TYPE,
)
from app.v2.errors import JobIncompleteError
from app.va.identifier import IdentifierType


SEND_TASK_MOCK_PATH = 'app.celery.tasks.notify_celery.send_task'
LOGGER_EXCEPTION_MOCK_PATH = 'app.celery.tasks.current_app.logger.exception'
ZENDEKS_CLIENT_CRREATE_TICKET_MOCK_PATH = 'app.celery.nightly_tasks.zendesk_client.create_ticket'


@pytest.fixture
def dynamodb_mock():
    """
    Mock the DynamoDB table.
    """

    bip_table_vars = {
        'TableName': 'TestTable',
        'AttributeDefinitions': [
            {'AttributeName': 'participant_id', 'AttributeType': 'N'},
            {
                'AttributeName': 'payment_id',
                'AttributeType': 'N',
            },
            {
                'AttributeName': 'vaprofile_id',
                'AttributeType': 'N',
            },
            {
                'AttributeName': 'is_update_allowed',
                'AttributeType': 'N',
            },
            {
                'AttributeName': 'is_processed',
                'AttributeType': 'S',
            },
        ],
        'KeySchema': [
            {'AttributeName': 'participant_id', 'KeyType': 'HASH'},
            {'AttributeName': 'payment_id', 'KeyType': 'RANGE'},
        ],
        'GlobalSecondaryIndexes': [
            {
                'IndexName': 'vaprofile-id-index',
                'KeySchema': [{'AttributeName': 'vaprofile_id', 'KeyType': 'HASH'}],
                'Projection': {
                    'ProjectionType': 'KEYS_ONLY',
                },
            },
            {
                'IndexName': 'is-update-allowed-index',
                'KeySchema': [{'AttributeName': 'is_update_allowed', 'KeyType': 'HASH'}],
                'Projection': {
                    'ProjectionType': 'ALL',
                },
            },
            {
                'IndexName': 'is-processed-index',
                'KeySchema': [{'AttributeName': 'is_processed', 'KeyType': 'HASH'}],
                'Projection': {
                    'ProjectionType': 'ALL',
                },
            },
        ],
        'BillingMode': 'PAY_PER_REQUEST',
    }
    with mock_dynamodb():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Create a mock DynamoDB table
        table = dynamodb.create_table(**bip_table_vars)

        # Wait for table to be created
        table.meta.client.get_waiter('table_exists').wait(TableName='TestTable')

        yield table


@pytest.fixture
def sample_dynamodb_insert(dynamodb_mock):
    items_inserted = []

    def _dynamodb_insert(items_to_insert: list):
        with dynamodb_mock.batch_writer() as batch:
            for item in items_to_insert:
                batch.put_item(Item=item)
                items_inserted.append(item)

    yield _dynamodb_insert

    # delete the items added
    for item in items_inserted:
        dynamodb_mock.delete_item(Key={'participant_id': item['participant_id'], 'payment_id': item['payment_id']})


@pytest.fixture
def setup_monetary_decimal_context():
    context = getcontext()
    initial_context = context.copy()
    context.prec = 2

    yield

    context = initial_context


def test_should_call_delete_codes_on_delete_verify_codes_task(notify_db_session, mocker):
    mocker.patch('app.celery.scheduled_tasks.delete_codes_older_created_more_than_a_day_ago')
    delete_verify_codes()
    assert scheduled_tasks.delete_codes_older_created_more_than_a_day_ago.call_count == 1


def test_should_call_delete_invotations_on_delete_invitations_task(notify_api, mocker):
    mocker.patch('app.celery.scheduled_tasks.delete_invitations_created_more_than_two_days_ago')
    delete_invitations()
    assert scheduled_tasks.delete_invitations_created_more_than_two_days_ago.call_count == 1


@pytest.mark.serial
def test_should_update_scheduled_jobs_and_put_on_queue(notify_db_session, mocker, sample_template, sample_job):
    mocked = mocker.patch('app.celery.tasks.process_job.apply_async')

    one_minute_in_the_past = datetime.utcnow() - timedelta(minutes=1)
    template = sample_template()
    job = sample_job(template, job_status=JOB_STATUS_SCHEDULED, scheduled_for=one_minute_in_the_past)

    # Does not work with multiple workers
    run_scheduled_jobs()

    notify_db_session.session.refresh(job)
    assert job.job_status == JOB_STATUS_PENDING
    mocked.assert_called_with([str(job.id)], queue='job-tasks')


def test_should_update_all_scheduled_jobs_and_put_on_queue(
    notify_api,
    mocker,
    sample_template,
    sample_job,
):
    mocked = mocker.patch('app.celery.tasks.process_job.apply_async')

    one_minute_in_the_past = datetime.utcnow() - timedelta(minutes=1)
    ten_minutes_in_the_past = datetime.utcnow() - timedelta(minutes=10)
    twenty_minutes_in_the_past = datetime.utcnow() - timedelta(minutes=20)
    template = sample_template()
    job_1 = sample_job(template, job_status=JOB_STATUS_SCHEDULED, scheduled_for=one_minute_in_the_past)
    job_2 = sample_job(template, job_status=JOB_STATUS_SCHEDULED, scheduled_for=ten_minutes_in_the_past)
    job_3 = sample_job(template, job_status=JOB_STATUS_SCHEDULED, scheduled_for=twenty_minutes_in_the_past)

    run_scheduled_jobs()

    assert dao_get_job_by_id(job_1.id).job_status == JOB_STATUS_PENDING
    assert dao_get_job_by_id(job_2.id).job_status == JOB_STATUS_PENDING
    assert dao_get_job_by_id(job_2.id).job_status == JOB_STATUS_PENDING

    mocked.assert_has_calls(
        [
            call([str(job_3.id)], queue='job-tasks'),
            call([str(job_2.id)], queue='job-tasks'),
            call([str(job_1.id)], queue='job-tasks'),
        ]
    )


@freeze_time('2017-05-01 14:00:00')
def test_should_send_all_scheduled_notifications_to_deliver_queue(mocker, sample_template, sample_notification):
    mocked_chain = mocker.patch('app.notifications.process_notifications.chain')
    mock_sms_sender = mocker.patch(
        'app.notifications.process_notifications.' 'dao_get_service_sms_sender_by_service_id_and_number'
    )
    mock_sms_sender.rate_limit = mocker.Mock()
    template = sample_template()
    message_to_deliver = sample_notification(template=template, scheduled_for='2017-05-01 13:15')
    sample_notification(template=template, scheduled_for='2017-05-01 10:15', status='delivered')
    sample_notification(template=template)
    sample_notification(template=template, scheduled_for='2017-05-01 14:15')

    scheduled_notifications = dao_get_scheduled_notifications()
    assert len(scheduled_notifications) == 1

    send_scheduled_notifications()

    args, _ = mocked_chain.call_args
    for called_task, expected_task in zip(args, ['send-sms-tasks']):
        assert called_task.options['queue'] == expected_task
        assert called_task.args[0] == str(message_to_deliver.id)

    scheduled_notifications = dao_get_scheduled_notifications()
    assert not scheduled_notifications


@pytest.mark.serial
def test_check_job_status_task_raises_job_incomplete_error(mocker, sample_template, sample_job, sample_notification):
    mock_celery = mocker.patch(SEND_TASK_MOCK_PATH)
    template = sample_template()
    job = sample_job(
        template,
        notification_count=3,
        created_at=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_IN_PROGRESS,
    )
    sample_notification(template=template, job=job)
    with pytest.raises(expected_exception=JobIncompleteError) as e:
        # Requires serial worker execution
        check_job_status()
    assert e.value.message == "Job(s) ['{}'] have not completed.".format(str(job.id))

    mock_celery.assert_called_once_with(
        name=TaskNames.PROCESS_INCOMPLETE_JOBS, args=([str(job.id)],), queue=QueueNames.JOBS
    )


@pytest.mark.serial
def test_check_job_status_task_raises_job_incomplete_error_when_scheduled_job_is_not_complete(
    mocker, sample_template, sample_job
):
    mock_celery = mocker.patch(SEND_TASK_MOCK_PATH)
    template = sample_template()
    job = sample_job(
        template,
        notification_count=3,
        created_at=datetime.utcnow() - timedelta(hours=2),
        scheduled_for=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_IN_PROGRESS,
    )
    with pytest.raises(expected_exception=JobIncompleteError) as e:
        # Requires serial worker execution
        check_job_status()
    assert e.value.message == "Job(s) ['{}'] have not completed.".format(str(job.id))

    mock_celery.assert_called_once_with(
        name=TaskNames.PROCESS_INCOMPLETE_JOBS, args=([str(job.id)],), queue=QueueNames.JOBS
    )


@pytest.mark.serial
def test_check_job_status_task_raises_job_incomplete_error_for_multiple_jobs(mocker, sample_template, sample_job):
    mock_celery = mocker.patch(SEND_TASK_MOCK_PATH)
    template = sample_template()
    job = sample_job(
        template,
        notification_count=3,
        created_at=datetime.utcnow() - timedelta(hours=2),
        scheduled_for=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_IN_PROGRESS,
    )
    job_2 = sample_job(
        template,
        notification_count=3,
        created_at=datetime.utcnow() - timedelta(hours=2),
        scheduled_for=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_IN_PROGRESS,
    )
    with pytest.raises(expected_exception=JobIncompleteError) as e:
        # Requires serial worker execution
        check_job_status()
    assert str(job.id) in e.value.message
    assert str(job_2.id) in e.value.message

    mock_celery.assert_called_once_with(
        name=TaskNames.PROCESS_INCOMPLETE_JOBS, args=([str(job.id), str(job_2.id)],), queue=QueueNames.JOBS
    )


@pytest.mark.serial
def test_check_job_status_task_only_sends_old_tasks(mocker, sample_template, sample_job):
    mock_celery = mocker.patch(SEND_TASK_MOCK_PATH)
    template = sample_template()
    job = sample_job(
        template,
        notification_count=3,
        created_at=datetime.utcnow() - timedelta(hours=2),
        scheduled_for=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_IN_PROGRESS,
    )
    job_2 = sample_job(
        template,
        notification_count=3,
        created_at=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=29),
        job_status=JOB_STATUS_IN_PROGRESS,
    )
    with pytest.raises(expected_exception=JobIncompleteError) as e:
        # Requires serial worker execution
        check_job_status()
    assert str(job.id) in e.value.message
    assert str(job_2.id) not in e.value.message

    # job 2 not in celery task
    mock_celery.assert_called_once_with(
        name=TaskNames.PROCESS_INCOMPLETE_JOBS, args=([str(job.id)],), queue=QueueNames.JOBS
    )


@pytest.mark.serial
def test_check_job_status_task_sets_jobs_to_error(mocker, sample_template, sample_job):
    mock_celery = mocker.patch(SEND_TASK_MOCK_PATH)
    template = sample_template()
    job = sample_job(
        template,
        notification_count=3,
        created_at=datetime.utcnow() - timedelta(hours=2),
        scheduled_for=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_IN_PROGRESS,
    )
    job_2 = sample_job(
        template,
        notification_count=3,
        created_at=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=29),
        job_status=JOB_STATUS_IN_PROGRESS,
    )
    with pytest.raises(expected_exception=JobIncompleteError) as e:
        # Requires serial worker execution
        check_job_status()
    assert str(job.id) in e.value.message
    assert str(job_2.id) not in e.value.message

    # job 2 not in celery task
    mock_celery.assert_called_once_with(
        name=TaskNames.PROCESS_INCOMPLETE_JOBS, args=([str(job.id)],), queue=QueueNames.JOBS
    )
    assert job.job_status == JOB_STATUS_ERROR
    assert job_2.job_status == JOB_STATUS_IN_PROGRESS


@freeze_time('1993-06-01')
@pytest.mark.parametrize(
    'notification_type, expected_delivery_status',
    [
        (EMAIL_TYPE, 'delivered'),
        (SMS_TYPE, 'sending'),
    ],
)
def test_replay_created_notifications(
    notify_api,
    client,
    mocker,
    notification_type,
    expected_delivery_status,
    sample_template,
    sample_notification,
):
    mocked = mocker.patch(f'app.celery.provider_tasks.deliver_{notification_type}.apply_async')
    older_than = (60 * 60 * 24) + (60 * 15)  # 24 hours 15 minutes
    template = sample_template(template_type=notification_type)

    old_notification = sample_notification(
        template=template, created_at=datetime.utcnow() - timedelta(seconds=older_than), status='created'
    )

    sample_notification(
        template=template, created_at=datetime.utcnow() - timedelta(seconds=older_than), status=expected_delivery_status
    )

    sample_notification(template=template, created_at=datetime.utcnow(), status='created')

    sample_notification(template=template, created_at=datetime.utcnow(), status='created')

    mock_sms_sender = mocker.Mock()
    mock_sms_sender.rate_limit = 1

    mocker.patch(
        'app.notifications.process_notifications.dao_get_service_sms_sender_by_service_id_and_number',
        return_value=mock_sms_sender,
    )

    replay_created_notifications()
    (result_notification_id, _), result_queue = mocked.call_args.args
    assert result_notification_id == str(old_notification.id)

    assert mocked.call_args.kwargs['queue'] == f'send-{notification_type}-tasks'
    mocked.assert_called_once()


@pytest.mark.serial
def test_check_job_status_task_does_not_raise_error(
    notify_api,
    sample_template,
    sample_job,
):
    template = sample_template()
    sample_job(
        template,
        notification_count=3,
        created_at=datetime.utcnow() - timedelta(hours=2),
        scheduled_for=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_FINISHED,
    )
    sample_job(
        template,
        notification_count=3,
        created_at=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_FINISHED,
    )

    # Requires serial worker execution
    check_job_status()


@freeze_time('2019-05-30 14:00:00')
def test_check_precompiled_letter_state(mocker, sample_template, sample_notification):
    mock_logger = mocker.patch(LOGGER_EXCEPTION_MOCK_PATH)
    mock_create_ticket = mocker.patch(ZENDEKS_CLIENT_CRREATE_TICKET_MOCK_PATH)
    template = sample_template(template_type=LETTER_TYPE)

    sample_notification(
        template=template,
        status=NOTIFICATION_PENDING_VIRUS_CHECK,
        created_at=datetime.utcnow() - timedelta(seconds=5400),
    )
    sample_notification(
        template=template, status=NOTIFICATION_DELIVERED, created_at=datetime.utcnow() - timedelta(seconds=6000)
    )
    noti_1 = sample_notification(
        template=template,
        status=NOTIFICATION_PENDING_VIRUS_CHECK,
        created_at=datetime.utcnow() - timedelta(seconds=5401),
    )
    noti_2 = sample_notification(
        template=template,
        status=NOTIFICATION_PENDING_VIRUS_CHECK,
        created_at=datetime.utcnow() - timedelta(seconds=70000),
    )

    check_precompiled_letter_state()

    message = (
        '2 precompiled letters have been pending-virus-check for over 90 minutes. '
        "Notifications: ['{}', '{}']".format(noti_2.id, noti_1.id)
    )

    mock_logger.assert_called_once_with(message)
    mock_create_ticket.assert_called_with(
        message=message, subject='[test] Letters still pending virus check', ticket_type='incident'
    )


def test_get_dynamodb_comp_pen_messages_with_empty_table(dynamodb_mock):
    # Invoke the function with the mocked table and application
    messages = _get_dynamodb_comp_pen_messages(dynamodb_mock, message_limit=1)

    assert messages == [], 'Expected no messages from an empty table'


def test_get_dynamodb_comp_pen_messages_filters(dynamodb_mock, sample_dynamodb_insert, setup_monetary_decimal_context):
    """
    Items should not be returned if any of these apply:
        2) has_duplicate_mappings is True
        3) payment_id equals -1
        4) paymentAmount is absent (required by downstream Celery task)
    """
    # Insert mock data into the DynamoDB table.
    items_to_insert = [
        # The first 2 items are valid.
        {'participant_id': 1, 'is_processed': 'F', 'payment_id': 1, 'paymentAmount': Decimal(1.00)},
        {
            'participant_id': 2,
            'is_processed': 'F',
            'has_duplicate_mappings': False,
            'payment_id': 2,
            'paymentAmount': Decimal(2.50),
        },
        # Already processed
        {'participant_id': 4, 'payment_id': 4, 'paymentAmount': Decimal(0)},
        # Duplicate mappings
        {
            'participant_id': 5,
            'is_processed': 'F',
            'has_duplicate_mappings': True,
            'payment_id': 5,
            'paymentAmount': Decimal('0.99'),
        },
        # Placeholder payment_id
        {'participant_id': 6, 'is_processed': 'F', 'payment_id': -1, 'paymentAmount': Decimal(1.00)},
        # Missing paymentAmount
        {'participant_id': 7, 'is_processed': 'F', 'payment_id': 1},
    ]
    sample_dynamodb_insert(items_to_insert)

    # Invoke the function with the mocked table and application
    messages = _get_dynamodb_comp_pen_messages(dynamodb_mock, message_limit=7)

    for msg in messages:
        assert (
            str(msg['participant_id']) in '12'
        ), f"The message with ID {msg['participant_id']} should have been filtered out."
    assert len(messages) == 2


def test_it_update_dynamo_item_is_processed_updates_properly(dynamodb_mock, sample_dynamodb_insert):
    items_to_insert = [
        {'participant_id': 1, 'is_processed': 'F', 'payment_id': 1, 'paymentAmount': Decimal(1.00)},
        {'participant_id': 2, 'is_processed': 'F', 'payment_id': 2, 'paymentAmount': Decimal(2.50)},
        {'participant_id': 3, 'payment_id': 1, 'paymentAmount': Decimal(0.00)},
    ]

    # Insert mock data into the DynamoDB table.
    sample_dynamodb_insert(items_to_insert)

    with dynamodb_mock.batch_writer() as batch:
        for item in items_to_insert:
            _update_dynamo_item_is_processed(batch, item)

    response = dynamodb_mock.scan()

    # Ensure we get all 3 records back and they are set with is_processed removed
    assert response['Count'] == 3
    for item in response['Items']:
        assert 'is_processed' not in item


def test_send_scheduled_comp_and_pen_sms_does_not_call_send_notification(mocker, dynamodb_mock):
    mocker.patch('app.celery.scheduled_tasks.is_feature_enabled', return_value=True)

    # Mocks necessary for dynamodb
    mocker.patch('boto3.resource')
    mocker.patch('boto3.resource.Table', return_value=dynamodb_mock)

    mocker.patch('app.celery.scheduled_tasks._get_dynamodb_comp_pen_messages', return_value=[])

    mock_send_notification = mocker.patch('app.celery.scheduled_tasks.send_notification_bypass_route')

    send_scheduled_comp_and_pen_sms()

    mock_send_notification.assert_not_called()


def test_ut_send_scheduled_comp_and_pen_sms_calls_send_notification_with_recipient(
    mocker, dynamodb_mock, sample_service, sample_template
):
    sample_service_sms_permission = sample_service(
        service_permissions=[
            SMS_TYPE,
        ]
    )

    # Set up test data
    dynamo_data = [
        {
            'participant_id': '123',
            'vaprofile_id': '123',
            'payment_id': '123',
            'paymentAmount': 123,
            'is_processed': False,
        },
    ]

    # Mock the comp and pen perf number for sending with recipient
    test_recipient = '+11234567890'
    mocker.patch.dict(
        'app.celery.scheduled_tasks.current_app.config',
        {
            'COMP_AND_PEN_SMS_SENDER_ID': '',
            'COMP_AND_PEN_PERF_TO_NUMBER': test_recipient,
        },
    )

    mocker.patch('app.celery.scheduled_tasks.is_feature_enabled', return_value=True)

    # Mocks necessary for dynamodb
    mocker.patch('boto3.resource')
    mocker.patch('boto3.resource.Table', return_value=dynamodb_mock)

    # Mock the various functions called
    mock_get_dynamodb_messages = mocker.patch(
        'app.celery.scheduled_tasks._get_dynamodb_comp_pen_messages', return_value=dynamo_data
    )
    mock_fetch_service = mocker.patch(
        'app.celery.scheduled_tasks.dao_fetch_service_by_id', return_value=sample_service_sms_permission
    )
    template = sample_template()
    mock_get_template = mocker.patch('app.celery.scheduled_tasks.dao_get_template_by_id', return_value=template)

    mock_send_notification = mocker.patch('app.celery.scheduled_tasks.send_notification_bypass_route')

    send_scheduled_comp_and_pen_sms()

    # Assert the functions are being called that should be
    mock_get_dynamodb_messages.assert_called_once()
    mock_fetch_service.assert_called_once()
    mock_get_template.assert_called_once()

    # Assert the expected information is passed to "send_notification_bypass_route"
    mock_send_notification.assert_called_once_with(
        service=sample_service_sms_permission,
        template=template,
        notification_type=SMS_TYPE,
        personalisation={'paymentAmount': '123'},
        sms_sender_id=sample_service_sms_permission.get_default_sms_sender_id(),
        recipient=test_recipient,
        recipient_item=None,
    )


def test_ut_send_scheduled_comp_and_pen_sms_calls_send_notification_with_recipient_item(
    mocker, dynamodb_mock, sample_service, sample_template
):
    sample_service_sms_permission = sample_service(
        service_permissions=[
            SMS_TYPE,
        ]
    )

    # Set up test data
    dynamo_data = [
        {
            'participant_id': '123',
            'vaprofile_id': '123',
            'payment_id': '123',
            'paymentAmount': 123,
            'is_processed': False,
        },
    ]

    recipient_item = {'id_type': IdentifierType.VA_PROFILE_ID.value, 'id_value': '123'}

    mocker.patch('app.celery.scheduled_tasks.is_feature_enabled', return_value=True)

    # Mocks necessary for dynamodb
    mocker.patch('boto3.resource')
    mocker.patch('boto3.resource.Table', return_value=dynamodb_mock)

    # Mock the various functions called
    mock_get_dynamodb_messages = mocker.patch(
        'app.celery.scheduled_tasks._get_dynamodb_comp_pen_messages', return_value=dynamo_data
    )
    mock_fetch_service = mocker.patch(
        'app.celery.scheduled_tasks.dao_fetch_service_by_id', return_value=sample_service_sms_permission
    )
    template = sample_template()
    mock_get_template = mocker.patch('app.celery.scheduled_tasks.dao_get_template_by_id', return_value=template)

    mock_send_notification = mocker.patch('app.celery.scheduled_tasks.send_notification_bypass_route')
    mocker.patch.dict('app.celery.scheduled_tasks.current_app.config', {'COMP_AND_PEN_SMS_SENDER_ID': ''})

    send_scheduled_comp_and_pen_sms()

    # Assert the functions are being called that should be
    mock_get_dynamodb_messages.assert_called_once()
    mock_fetch_service.assert_called_once()
    mock_get_template.assert_called_once()

    # Assert the expected information is passed to "send_notification_bypass_route"
    mock_send_notification.assert_called_once_with(
        service=sample_service_sms_permission,
        template=template,
        notification_type=SMS_TYPE,
        personalisation={'paymentAmount': '123'},
        sms_sender_id=sample_service_sms_permission.get_default_sms_sender_id(),
        recipient=None,
        recipient_item=recipient_item,
    )


def test_send_scheduled_comp_and_pen_sms_uses_batch_write(mocker, sample_service, sample_template):
    mocker.patch('app.celery.scheduled_tasks.is_feature_enabled', return_value=True)
    mocker.patch('app.celery.scheduled_tasks.send_notification_bypass_route')

    sample_service_sms_permission = sample_service(
        service_permissions=[
            SMS_TYPE,
        ]
    )
    mocker.patch('app.celery.scheduled_tasks.dao_fetch_service_by_id', return_value=sample_service_sms_permission)
    template = sample_template()
    mocker.patch('app.celery.scheduled_tasks.dao_get_template_by_id', return_value=template)

    dynamo_data = [
        {
            'participant_id': '123',
            'vaprofile_id': '123',
            'payment_id': '123',
            'paymentAmount': 123,
            'is_processed': False,
        },
    ]
    mocker.patch('app.celery.scheduled_tasks._get_dynamodb_comp_pen_messages', return_value=dynamo_data)
    mocker.patch.dict('app.celery.scheduled_tasks.current_app.config', {'COMP_AND_PEN_SMS_SENDER_ID': ''})

    with patch('app.celery.scheduled_tasks.boto3.resource') as mock_resource:
        mock_put_item = MagicMock()
        mock_resource.return_value.Table.return_value.batch_writer.return_value.__enter__.return_value.put_item = (
            mock_put_item
        )

        send_scheduled_comp_and_pen_sms()

    dynamo_data[0]['is_processed'] = True
    mock_put_item.assert_called_once_with(Item=dynamo_data[0])


@pytest.mark.parametrize('sms_sender_id', ('This is not a UUID.', 'd1abbb27-9c72-4de4-8463-dbdf24d3fdd6'))
def test_wt_send_scheduled_comp_and_pen_sms_sms_sender_id_selection(
    mocker, sample_service, sample_template, sms_sender_id, dynamodb_mock
):
    """
    When the configuration variable COMP_AND_PEN_SMS_SENDER_ID is a valid UUID, the task send_scheduled_comp_and_pen_sms
    should send notifications using the ServiceSmsSender associated with that UUID.  Otherwise, the task should use the
    default SMS sender associated with the service referenced by the configuration variable COMP_AND_PEN_SERVICE_ID.
    """

    mocker.patch('boto3.resource')
    mocker.patch('boto3.resource.Table', return_value=dynamodb_mock)

    items = [
        {
            'participant_id': '123',
            'vaprofile_id': '123',
            'payment_id': '123',
            'paymentAmount': 123,
            'is_processed': False,
        },
    ]
    mocker.patch('app.celery.scheduled_tasks._get_dynamodb_comp_pen_messages', return_value=items)
    mock_send_notification = mocker.patch('app.celery.scheduled_tasks.send_notification_bypass_route')
    mocker.patch('app.celery.scheduled_tasks._update_dynamo_item_is_processed')

    service = sample_service()
    template = sample_template()

    mocker.patch.dict(
        'app.celery.scheduled_tasks.current_app.config',
        {
            'COMP_AND_PEN_SERVICE_ID': service.id,
            'COMP_AND_PEN_TEMPLATE_ID': template.id,
            'COMP_AND_PEN_SMS_SENDER_ID': sms_sender_id,
            'COMP_AND_PEN_PERF_TO_NUMBER': '+15552225566',
        },
    )

    with patch.dict('os.environ', {'COMP_AND_PEN_MESSAGES_ENABLED': 'True'}):
        send_scheduled_comp_and_pen_sms()

    try:
        # If this line doesn't raise ValueError, sms_sender_id is a valid UUID.
        expected_sms_sender_id = UUID(sms_sender_id)
    except ValueError:
        expected_sms_sender_id = service.get_default_sms_sender_id()

    mock_send_notification.assert_called_once_with(
        service=ANY,
        template=ANY,
        notification_type=SMS_TYPE,
        personalisation={'paymentAmount': '123'},
        sms_sender_id=expected_sms_sender_id,
        recipient='+15552225566',
        recipient_item=None,
    )
    assert mock_send_notification.call_args.kwargs['service'].id == service.id
    assert mock_send_notification.call_args.kwargs['template'].id == template.id
