from datetime import date, datetime, timedelta
from uuid import uuid4

from app.dao.notifications_dao import (
    delete_notifications_older_than_retention_by_type,
    insert_update_notification_history,
)
from app.models import (
    Notification,
    NotificationHistory,
    RecipientIdentifier,
    EMAIL_TYPE,
    LETTER_TYPE,
    SMS_TYPE,
)
from app.notifications.process_notifications import persist_notification
from app.va.identifier import IdentifierType
from flask import current_app
from freezegun import freeze_time
import pytest
from sqlalchemy import delete, select, update


def create_test_data(
    notification_type,
    sample_service,
    sample_template,
    sample_notification,
    sample_service_data_retention,
    days_of_retention=3,
):
    service_with_default_data_retention = sample_service()
    retention_service = sample_service()
    email_template, letter_template, sms_template = _create_templates(
        sample_service, sample_template, retention_service
    )
    default_email_template, default_letter_template, default_sms_template = _create_templates(
        sample_service, sample_template, service_with_default_data_retention
    )
    sample_notification(template=email_template, status='delivered')
    sample_notification(template=sms_template, status='permanent-failure')
    sample_notification(
        template=letter_template, status='temporary-failure', reference='LETTER_REF', sent_at=datetime.utcnow()
    )
    sample_notification(template=email_template, status='delivered', created_at=datetime.utcnow() - timedelta(days=4))
    sample_notification(
        template=sms_template, status='permanent-failure', created_at=datetime.utcnow() - timedelta(days=4)
    )
    sample_notification(
        template=letter_template,
        status='temporary-failure',
        reference='LETTER_REF',
        sent_at=datetime.utcnow(),
        created_at=datetime.utcnow() - timedelta(days=4),
    )
    sample_notification(
        template=default_email_template, status='delivered', created_at=datetime.utcnow() - timedelta(days=8)
    )
    sample_notification(
        template=default_sms_template, status='permanent-failure', created_at=datetime.utcnow() - timedelta(days=8)
    )
    sample_notification(
        template=default_letter_template,
        status='temporary-failure',
        reference='LETTER_REF',
        sent_at=datetime.utcnow(),
        created_at=datetime.utcnow() - timedelta(days=8),
    )

    service_data_retention = sample_service_data_retention(
        service=email_template.service, notification_type=notification_type, days_of_retention=days_of_retention
    )

    return service_with_default_data_retention, retention_service, service_data_retention


def _create_templates(
    sample_service,
    sample_template,
    service=None,
):
    if service is None:
        service = sample_service()

    sms_template = sample_template(service=service)
    email_template = sample_template(service=service, template_type=EMAIL_TYPE)
    letter_template = sample_template(service=service, template_type=LETTER_TYPE)
    return email_template, letter_template, sms_template


@pytest.mark.serial
@pytest.mark.parametrize(
    'month, delete_run_time',
    [
        (4, '2016-04-10 23:40'),
        (1, '2016-01-11 00:40'),
    ],
)
@pytest.mark.parametrize(
    'notification_type, expected_sms_count, expected_email_count, expected_letter_count',
    [
        (EMAIL_TYPE, 10, 7, 10),
        (LETTER_TYPE, 10, 10, 7),
        (SMS_TYPE, 7, 10, 10),
    ],
)
def test_should_delete_notifications_by_type_after_seven_days(
    mocker,
    notify_db_session,
    sample_service,
    sample_template,
    sample_notification,
    month,
    delete_run_time,
    notification_type,
    expected_sms_count,
    expected_email_count,
    expected_letter_count,
):
    mocker.patch('app.dao.notifications_dao.get_s3_bucket_objects')
    email_template, letter_template, sms_template = _create_templates(sample_service, sample_template)
    service = email_template.service

    # For each notification type, create one notification a day between the 1st and 10th from 11:00 to 19:00.
    for i in range(1, 11):
        past_date = '2016-0{0}-{1:02d}  {1:02d}:00:00.000000'.format(month, i)
        with freeze_time(past_date):
            sample_notification(template=email_template, created_at=datetime.utcnow(), status='permanent-failure')
            sample_notification(template=sms_template, created_at=datetime.utcnow(), status='delivered')
            sample_notification(template=letter_template, created_at=datetime.utcnow(), status='temporary-failure')

    stmt = select(Notification).where(Notification.service_id == service.id)
    assert len(notify_db_session.session.scalars(stmt).all()) == 30

    # Records from before the 3rd should be deleted.
    with freeze_time(delete_run_time):
        # Requires serial processing
        delete_notifications_older_than_retention_by_type(notification_type)

    sms_stmt = stmt.where(Notification.notification_type == SMS_TYPE)
    remaining_sms_notifications = notify_db_session.session.scalars(sms_stmt).all()

    letter_stmt = stmt.where(Notification.notification_type == LETTER_TYPE)
    remaining_letter_notifications = notify_db_session.session.scalars(letter_stmt).all()

    email_stmt = stmt.where(Notification.notification_type == EMAIL_TYPE)
    remaining_email_notifications = notify_db_session.session.scalars(email_stmt).all()

    assert len(remaining_sms_notifications) == expected_sms_count
    assert len(remaining_email_notifications) == expected_email_count
    assert len(remaining_letter_notifications) == expected_letter_count

    if notification_type == SMS_TYPE:
        notifications_to_check = remaining_sms_notifications
    elif notification_type == EMAIL_TYPE:
        notifications_to_check = remaining_email_notifications
    elif notification_type == LETTER_TYPE:
        notifications_to_check = remaining_letter_notifications

    for notification in notifications_to_check:
        assert notification.created_at.date() >= date(2016, month, 3)


@pytest.mark.serial
@pytest.mark.parametrize(
    'month, delete_run_time',
    [
        (4, '2016-04-10 23:40'),
        (1, '2016-01-11 00:40'),
    ],
)
@pytest.mark.parametrize(
    'notification_type, expected_count',
    [
        (EMAIL_TYPE, 7),
        (SMS_TYPE, 7),
    ],
)
def test_should_delete_notification_and_recipient_identifiers_when_bulk_deleting(
    month,
    delete_run_time,
    notification_type,
    expected_count,
    sample_template,
    sample_api_key,
    mocker,
    notify_db_session,
):
    mocker.patch('app.notifications.process_notifications.accept_recipient_identifiers_enabled', return_value=True)

    api_key = sample_api_key()
    template = sample_template(template_type=notification_type)

    notification_ids = []
    # Create one notification a day of each type between the 1st and 10th from 11:00 to 19:00.
    for i in range(1, 11):
        past_date = '2016-0{0}-{1:02d}  {1:02d}:00:00.000000'.format(month, i)
        with freeze_time(past_date):
            recipient_identifier = {'id_type': IdentifierType.VA_PROFILE_ID.value, 'id_value': 'foo'}
            notification = persist_notification(
                template_id=template.id,
                template_version=template.version,
                service_id=template.service.id,
                personalisation=None,
                notification_type=notification_type,
                api_key_id=api_key.id,
                key_type=api_key.key_type,
                recipient_identifier=recipient_identifier,
                created_at=datetime.utcnow(),
            )
            notification_ids.append(notification.id)

    stmt = select(Notification).where(Notification.template_id == template.id)
    assert len(notify_db_session.session.scalars(stmt).all()) == 10

    stmt = select(RecipientIdentifier).where(RecipientIdentifier.notification_id.in_(notification_ids))
    assert len(notify_db_session.session.scalars(stmt).all()) == 10

    # Records from before 3rd should be deleted
    with freeze_time(delete_run_time):
        # Requires serial processing
        delete_notifications_older_than_retention_by_type(notification_type)

    try:
        stmt = select(Notification).where(Notification.notification_type == notification_type)
        remaining_notifications = notify_db_session.session.scalars(stmt).all()
        remaining_notification_ids = [n.id for n in remaining_notifications]
        deleted_notification_ids = set(notification_ids) - set(remaining_notification_ids)

        # Validate deleted are no longer in the recipient_identifiers
        stmt = select(RecipientIdentifier).where(RecipientIdentifier.notification_id.in_(deleted_notification_ids))
        failed_delete_recipient_identifiers = notify_db_session.session.scalars(stmt).all()

        stmt = select(RecipientIdentifier).where(RecipientIdentifier.notification_id.in_(remaining_notification_ids))
        remaining_recipient_identifiers = notify_db_session.session.scalars(stmt).all()

        # Moved asserts to the end due to cleanup
        assert len(remaining_notifications) == expected_count
        assert len(remaining_recipient_identifiers) == expected_count
        assert len(failed_delete_recipient_identifiers) == 0
    finally:
        # Teardown
        for notification_id in notification_ids:
            stmt = delete(Notification).where(Notification.id == notification_id)
            notify_db_session.session.execute(stmt)
            stmt = delete(NotificationHistory).where(NotificationHistory.id == notification_id)
            notify_db_session.session.execute(stmt)
        for recipient_identifier in remaining_recipient_identifiers:
            notify_db_session.session.delete(recipient_identifier)
        notify_db_session.session.commit()


@pytest.mark.serial
@freeze_time('2016-01-10 12:00:00.000000')
def test_should_not_delete_notification_history(
    notify_db_session,
    sample_service,
    sample_template,
    sample_notification,
    mocker,
):
    mocker.patch('app.dao.notifications_dao.get_s3_bucket_objects')
    with freeze_time('2016-01-01 12:00'):
        email_template, letter_template, sms_template = _create_templates(sample_service, sample_template)

        notification1 = sample_notification(template=email_template, status='permanent-failure')
        notification2 = sample_notification(template=sms_template, status='permanent-failure')
        notification3 = sample_notification(template=letter_template, status='permanent-failure')

    notification_id1 = notification1.id
    notification_id2 = notification2.id
    notification_id3 = notification3.id

    # This should delete notification2 because it is an SMS notification.
    # Requires serial processing
    delete_notifications_older_than_retention_by_type(SMS_TYPE)

    assert notify_db_session.session.get(Notification, notification_id1) is not None
    assert notify_db_session.session.get(Notification, notification_id2) is None
    assert notify_db_session.session.get(Notification, notification_id3) is not None

    # notification2 should have been moved to history.
    assert notify_db_session.session.get(NotificationHistory, notification_id1) is None
    assert notify_db_session.session.get(NotificationHistory, notification_id2) is not None
    assert notify_db_session.session.get(NotificationHistory, notification_id3) is None


@pytest.mark.serial
@pytest.mark.parametrize('notification_type', [SMS_TYPE, EMAIL_TYPE, LETTER_TYPE])
def test_delete_notifications_for_days_of_retention(
    notify_db_session,
    sample_service,
    sample_template,
    sample_notification,
    notification_type,
    mocker,
    sample_service_data_retention,
):
    mock_get_s3 = mocker.patch('app.dao.notifications_dao.get_s3_bucket_objects')

    default_service, retention_service, _ = create_test_data(
        notification_type,
        sample_service,
        sample_template,
        sample_notification,
        sample_service_data_retention,
    )

    stmt = select(Notification).where(Notification.service_id.in_((default_service.id, retention_service.id)))
    assert len(notify_db_session.session.scalars(stmt).all()) == 9

    # Requires serial processing
    delete_notifications_older_than_retention_by_type(notification_type)
    assert len(notify_db_session.session.scalars(stmt).all()) == 7

    stmt = stmt.where(Notification.notification_type == notification_type)
    assert len(notify_db_session.session.scalars(stmt).all()) == 1
    if notification_type == LETTER_TYPE:
        mock_get_s3.assert_called_with(
            bucket_name=current_app.config['LETTERS_PDF_BUCKET_NAME'],
            subfolder='{}/NOTIFY.LETTER_REF.D.2.C.C'.format(str(datetime.utcnow().date())),
        )
        assert mock_get_s3.call_count == 2
    else:
        mock_get_s3.assert_not_called()


@pytest.mark.serial
def test_delete_notifications_inserts_notification_history(
    notify_db_session,
    sample_service,
    sample_template,
    sample_notification,
    sample_service_data_retention,
):
    default_service, retention_service, _ = create_test_data(
        SMS_TYPE,
        sample_service,
        sample_template,
        sample_notification,
        sample_service_data_retention,
    )

    stmt = select(Notification).where(Notification.service_id.in_((default_service.id, retention_service.id)))
    notifications = notify_db_session.session.scalars(stmt).all()
    notification_ids = [n.id for n in notifications]
    assert len(notifications) == 9

    # `notifications` loses state when we make this delete method
    # Requires serial processing
    delete_notifications_older_than_retention_by_type(SMS_TYPE)
    assert len(notify_db_session.session.scalars(stmt).all()) == 7

    stmt = select(NotificationHistory).where(NotificationHistory.id.in_(notification_ids))
    assert len(notify_db_session.session.scalars(stmt).all()) == 2


@pytest.mark.serial
def test_delete_notifications_updates_notification_history(
    notify_db_session,
    sample_template,
    sample_notification,
    mocker,
):
    mocker.patch('app.dao.notifications_dao.get_s3_bucket_objects')
    template = sample_template(template_type=EMAIL_TYPE)
    notification = sample_notification(template=template, created_at=datetime.utcnow() - timedelta(days=8))

    stmt = (
        update(Notification)
        .where(Notification.id == notification.id)
        .values(
            status='delivered',
            reference='ses_reference',
            billable_units=2,  # Not updated for emails, but this is a unit test
            updated_at=datetime.utcnow(),
            sent_at=datetime.utcnow(),
            sent_by='ses',
        )
    )
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()

    # Requires serial processing
    delete_notifications_older_than_retention_by_type(EMAIL_TYPE)

    stmt = select(NotificationHistory).where(NotificationHistory.template_id == template.id)
    history = notify_db_session.session.scalars(stmt).all()
    assert len(history) == 1
    assert history[0].status == 'delivered'
    assert history[0].reference == 'ses_reference'
    assert history[0].billable_units == 2
    assert history[0].updated_at
    assert history[0].sent_by == 'ses'


@pytest.mark.serial
def test_delete_notifications_keep_data_for_days_of_retention_is_longer(
    notify_db_session,
    sample_service,
    sample_template,
    sample_notification,
    sample_service_data_retention,
):
    default_service, retention_service, _ = create_test_data(
        SMS_TYPE,
        sample_service,
        sample_template,
        sample_notification,
        sample_service_data_retention,
        15,
    )
    stmt = select(Notification).where(Notification.service_id.in_((default_service.id, retention_service.id)))
    assert len(notify_db_session.session.scalars(stmt).all()) == 9

    # Requires serial processing
    delete_notifications_older_than_retention_by_type(SMS_TYPE)
    assert len(notify_db_session.session.scalars(stmt).all()) == 8

    stmt = stmt.where(Notification.notification_type == SMS_TYPE)
    assert len(notify_db_session.session.scalars(stmt).all()) == 2


@pytest.mark.serial
def test_delete_notifications_with_test_keys(
    notify_db_session,
    sample_template,
    sample_notification,
    mocker,
):
    mocker.patch('app.dao.notifications_dao.get_s3_bucket_objects')
    template = sample_template()
    sample_notification(template=template, key_type='test', created_at=datetime.utcnow() - timedelta(days=8))

    # Requires serial processing
    delete_notifications_older_than_retention_by_type(SMS_TYPE)
    stmt = select(Notification).where(Notification.template_id == template.id)
    assert len(notify_db_session.session.scalars(stmt).all()) == 0


@pytest.mark.serial
def test_delete_notifications_delete_notification_type_for_default_time_if_no_days_of_retention_for_type(
    notify_db_session,
    sample_service,
    sample_template,
    sample_notification,
    sample_service_data_retention,
):
    email_template, letter_template, sms_template = _create_templates(sample_service, sample_template)
    # Same for all three templates
    service = email_template.service

    # Retention should apply to the service associated with the above templates.
    assert email_template.service.id == letter_template.service.id
    assert sms_template.service.id == letter_template.service.id
    sample_service_data_retention(service=email_template.service, notification_type=SMS_TYPE, days_of_retention=15)

    sample_notification(template=email_template, status='delivered')
    sample_notification(template=sms_template, status='permanent-failure')
    sample_notification(template=letter_template, status='temporary-failure')
    sample_notification(template=email_template, status='delivered', created_at=datetime.utcnow() - timedelta(days=14))
    sample_notification(
        template=sms_template, status='permanent-failure', created_at=datetime.utcnow() - timedelta(days=14)
    )
    sample_notification(
        template=letter_template, status='temporary-failure', created_at=datetime.utcnow() - timedelta(days=14)
    )

    # Validate correct number are in the DB
    stmt = select(Notification).where(Notification.service_id == service.id)
    assert len(notify_db_session.session.scalars(stmt).all()) == 6

    # Delete the one email type past retention & validate
    # Requires serial processing
    delete_notifications_older_than_retention_by_type(EMAIL_TYPE)
    assert len(notify_db_session.session.scalars(stmt).all()) == 5

    # Validate the other email notification is still there
    stmt = stmt.where(Notification.notification_type == EMAIL_TYPE)
    assert len(notify_db_session.session.scalars(stmt).all()) == 1


@pytest.mark.serial
def test_delete_notifications_does_try_to_delete_from_s3_when_letter_has_not_been_sent(
    mocker,
    sample_template,
    sample_notification,
):
    mock_get_s3 = mocker.patch('app.dao.notifications_dao.get_s3_bucket_objects')
    letter_template = sample_template(template_type=LETTER_TYPE)

    sample_notification(template=letter_template, status='sending', reference='LETTER_REF')
    # Requires serial processing
    delete_notifications_older_than_retention_by_type(EMAIL_TYPE, qry_limit=1)
    mock_get_s3.assert_not_called()


@pytest.mark.serial
@freeze_time('2016-01-10 12:00:00.000000')
def test_should_not_delete_notification_if_history_does_not_exist(
    notify_db_session,
    mocker,
    sample_service,
    sample_template,
    sample_notification,
):
    mocker.patch('app.dao.notifications_dao.get_s3_bucket_objects')
    mocker.patch('app.dao.notifications_dao.insert_update_notification_history')
    with freeze_time('2016-01-01 12:00'):
        email_template, letter_template, sms_template = _create_templates(sample_service, sample_template)
        sample_notification(template=email_template, status='permanent-failure')
        sample_notification(template=sms_template, status='delivered')
        sample_notification(template=letter_template, status='temporary-failure')
    service = email_template.service

    # Validate correct number are in the DB
    stmt = select(Notification).where(Notification.service_id == service.id)
    assert len(notify_db_session.session.scalars(stmt).all()) == 3

    # Delete zero notifications
    # Requires serial processing
    delete_notifications_older_than_retention_by_type(SMS_TYPE)
    assert len(notify_db_session.session.scalars(stmt).all()) == 3

    stmt = select(NotificationHistory).where(NotificationHistory.service_id == service.id)
    assert len(notify_db_session.session.scalars(stmt).all()) == 0


@pytest.mark.serial
def test_delete_notifications_calls_subquery_multiple_times(
    notify_db_session,
    sample_template,
    sample_notification,
):
    template = sample_template()
    sample_notification(template=template, created_at=datetime.now() - timedelta(days=8))
    sample_notification(template=template, created_at=datetime.now() - timedelta(days=8))
    sample_notification(template=template, created_at=datetime.now() - timedelta(days=8))

    service = template.service

    # Validate correct number are in the DB
    stmt = select(Notification).where(Notification.service_id == service.id)
    assert len(notify_db_session.session.scalars(stmt).all()) == 3

    # Requires serial processing
    delete_notifications_older_than_retention_by_type(SMS_TYPE, qry_limit=1)
    assert len(notify_db_session.session.scalars(stmt).all()) == 0


@pytest.mark.serial
def test_delete_notifications_returns_sum_correctly(sample_service, sample_template, sample_notification):
    template = sample_template()
    sample_notification(template=template, created_at=datetime.now() - timedelta(days=8))
    sample_notification(template=template, created_at=datetime.now() - timedelta(days=8))

    s2 = sample_service(service_name='s2')
    t2 = sample_template(service=s2, template_type=SMS_TYPE)
    assert template.service.id != t2.service.id
    sample_notification(template=t2, created_at=datetime.now() - timedelta(days=8))
    sample_notification(template=t2, created_at=datetime.now() - timedelta(days=8))

    # Requires serial processing
    ret = delete_notifications_older_than_retention_by_type(SMS_TYPE, qry_limit=1)
    assert ret == 4


def test_insert_update_notification_history(
    notify_db_session,
    sample_service,
    sample_template,
    sample_notification,
):
    service = sample_service()
    template = sample_template(service=service, template_type=SMS_TYPE)
    notification_1 = sample_notification(template=template, created_at=datetime.utcnow() - timedelta(days=3))
    notification_2 = sample_notification(template=template, created_at=datetime.utcnow() - timedelta(days=8))
    notification_3 = sample_notification(template=template, created_at=datetime.utcnow() - timedelta(days=9))
    other_types = [EMAIL_TYPE, LETTER_TYPE]
    for template_type in other_types:
        t = sample_template(service=service, template_type=template_type)
        sample_notification(template=t, created_at=datetime.utcnow() - timedelta(days=3))
        sample_notification(template=t, created_at=datetime.utcnow() - timedelta(days=8))

    insert_update_notification_history(
        notification_type=SMS_TYPE, date_to_delete_from=datetime.utcnow() - timedelta(days=7), service_id=service.id
    )

    stmt = select(NotificationHistory).where(NotificationHistory.service_id == service.id)
    history = notify_db_session.session.scalars(stmt).all()
    assert len(history) == 2

    history_ids = [x.id for x in history]
    assert notification_1.id not in history_ids
    assert notification_2.id in history_ids
    assert notification_3.id in history_ids


def test_insert_update_notification_history_only_insert_update_given_service(
    notify_db_session,
    sample_template,
    sample_notification,
):
    template = sample_template()
    other_template = sample_template()
    assert template.service.id != other_template.service.id

    notification_1 = sample_notification(template=template, created_at=datetime.utcnow() - timedelta(days=3))
    notification_2 = sample_notification(template=template, created_at=datetime.utcnow() - timedelta(days=8))
    notification_3 = sample_notification(template=other_template, created_at=datetime.utcnow() - timedelta(days=3))
    notification_4 = sample_notification(template=other_template, created_at=datetime.utcnow() - timedelta(days=8))

    insert_update_notification_history(SMS_TYPE, datetime.utcnow() - timedelta(days=7), template.service.id)

    stmt = select(NotificationHistory).where(
        NotificationHistory.service_id.in_((template.service.id, other_template.service.id))
    )
    history = notify_db_session.session.scalars(stmt).all()
    assert len(history) == 1

    history_ids = [x.id for x in history]
    assert notification_1.id not in history_ids
    assert notification_2.id in history_ids
    assert notification_3.id not in history_ids
    assert notification_4.id not in history_ids


def test_insert_update_notification_history_updates_history_with_new_status(
    notify_db_session,
    sample_template,
    sample_notification,
):
    template = sample_template()
    notification_1 = sample_notification(template=template, created_at=datetime.utcnow() - timedelta(days=3))
    notification_2 = sample_notification(
        template=template, created_at=datetime.utcnow() - timedelta(days=8), status='delivered'
    )
    insert_update_notification_history(SMS_TYPE, datetime.utcnow() - timedelta(days=7), template.service_id)

    stmt = select(NotificationHistory).where(NotificationHistory.id == notification_2.id)
    history = notify_db_session.session.scalar(stmt)
    assert history.status == 'delivered'
    assert notify_db_session.session.get(NotificationHistory, notification_1.id) is None


def test_insert_update_notification_history_updates_history_with_billing_code(
    notify_db_session,
    sample_template,
    sample_notification,
):
    template = sample_template()
    billing_code = str(uuid4())
    notification_1 = sample_notification(template=template, created_at=datetime.utcnow() - timedelta(days=3))
    notification_2 = sample_notification(
        template=template,
        created_at=datetime.utcnow() - timedelta(days=8),
        billing_code=billing_code,
    )
    insert_update_notification_history(SMS_TYPE, datetime.utcnow() - timedelta(days=7), template.service_id)

    stmt = select(NotificationHistory).where(NotificationHistory.id == notification_2.id)
    history = notify_db_session.session.scalar(stmt)
    assert history.billing_code == billing_code
    assert notify_db_session.session.get(NotificationHistory, notification_1.id) is None
