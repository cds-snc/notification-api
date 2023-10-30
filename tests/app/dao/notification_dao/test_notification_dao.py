import uuid
from datetime import datetime, timedelta
from functools import partial

import pytest
from freezegun import freeze_time
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm.exc import NoResultFound


from app.dao.notifications_dao import (
    dao_create_notification,
    dao_created_scheduled_notification,
    dao_delete_notification_by_id,
    dao_get_last_notification_added_for_job_id,
    dao_get_last_template_usage,
    dao_get_notifications_by_to_field,
    dao_get_scheduled_notifications,
    dao_timeout_notifications,
    dao_update_notification,
    dao_update_notifications_by_reference,
    delete_notifications_older_than_retention_by_type,
    get_notification_by_id,
    get_notification_for_job,
    get_notification_with_personalisation,
    get_notifications_for_job,
    get_notifications_for_service,
    is_delivery_slow_for_provider,
    set_scheduled_notification_to_processed,
    update_notification_status_by_id,
    update_notification_status_by_reference,
    dao_get_notification_by_reference,
    dao_get_notifications_by_references,
    dao_get_notification_history_by_reference,
    notifications_not_yet_sent,
)
from app.models import (
    Job,
    Notification,
    NotificationHistory,
    ScheduledNotification,
    NOTIFICATION_CREATED,
    NOTIFICATION_STATUS_TYPES,
    NOTIFICATION_STATUS_TYPES_FAILED,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_SENDING,
    NOTIFICATION_PENDING,
    NOTIFICATION_PENDING_VIRUS_CHECK,
    NOTIFICATION_SENT,
    NOTIFICATION_DELIVERED,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    JOB_STATUS_IN_PROGRESS,
    RecipientIdentifier,
    NOTIFICATION_PERMANENT_FAILURE,
    EMAIL_TYPE,
    LETTER_TYPE,
    SMS_TYPE,
)
from app.notifications.process_notifications import persist_notification
from app.va.identifier import IdentifierType
from tests.app.db import (
    create_job,
    create_notification,
    create_service,
    create_template,
    create_notification_history,
)


def test_should_have_decorated_notifications_dao_functions():
    assert dao_get_last_template_usage.__wrapped__.__name__ == 'dao_get_last_template_usage'  # noqa
    assert dao_create_notification.__wrapped__.__name__ == 'dao_create_notification'  # noqa
    assert update_notification_status_by_id.__wrapped__.__name__ == 'update_notification_status_by_id'  # noqa
    assert dao_update_notification.__wrapped__.__name__ == 'dao_update_notification'  # noqa
    assert update_notification_status_by_reference.__wrapped__.__name__ == 'update_notification_status_by_reference'  # noqa
    assert get_notification_for_job.__wrapped__.__name__ == 'get_notification_for_job'  # noqa
    assert get_notifications_for_job.__wrapped__.__name__ == 'get_notifications_for_job'  # noqa
    assert get_notification_with_personalisation.__wrapped__.__name__ == 'get_notification_with_personalisation'  # noqa
    assert get_notifications_for_service.__wrapped__.__name__ == 'get_notifications_for_service'  # noqa
    assert get_notification_by_id.__wrapped__.__name__ == 'get_notification_by_id'  # noqa
    assert delete_notifications_older_than_retention_by_type.__wrapped__.__name__ == 'delete_notifications_older_than_retention_by_type'  # noqa
    assert dao_delete_notification_by_id.__wrapped__.__name__ == 'dao_delete_notification_by_id'  # noqa


def test_should_by_able_to_update_status_by_reference(sample_email_template, ses_provider):
    data = _notification_json(sample_email_template, status='sending')

    notification = Notification(**data)
    dao_create_notification(notification)

    assert Notification.query.get(notification.id).status == "sending"
    notification.reference = 'reference'
    dao_update_notification(notification)

    updated = update_notification_status_by_reference('reference', 'delivered')
    assert updated.status == 'delivered'
    assert Notification.query.get(notification.id).status == 'delivered'


def test_should_by_able_to_update_status_by_id(sample_template, sample_job, mmg_provider):
    with freeze_time('2000-01-01 12:00:00'):
        data = _notification_json(sample_template, job_id=sample_job.id, status='sending')
        notification = Notification(**data)
        dao_create_notification(notification)
        assert notification.status == 'sending'

    assert Notification.query.get(notification.id).status == 'sending'

    with freeze_time('2000-01-02 12:00:00'):
        updated = update_notification_status_by_id(notification.id, 'delivered')

    assert updated.status == 'delivered'
    assert updated.updated_at == datetime(2000, 1, 2, 12, 0, 0)
    assert Notification.query.get(notification.id).status == 'delivered'
    assert notification.updated_at == datetime(2000, 1, 2, 12, 0, 0)
    assert notification.status == 'delivered'


def test_should_not_update_status_by_id_if_not_sending_and_does_not_update_job(sample_job):
    notification = create_notification(template=sample_job.template, status='delivered', job=sample_job)
    assert Notification.query.get(notification.id).status == 'delivered'
    assert not update_notification_status_by_id(notification.id, 'failed')
    assert Notification.query.get(notification.id).status == 'delivered'
    assert sample_job == Job.query.get(notification.job_id)


def test_should_not_update_status_by_reference_if_not_sending_and_does_not_update_job(sample_job):
    notification = create_notification(
        template=sample_job.template, status=NOTIFICATION_DELIVERED, reference='reference', job=sample_job
    )
    assert Notification.query.get(notification.id).status == NOTIFICATION_DELIVERED
    assert not update_notification_status_by_reference('reference', NOTIFICATION_PERMANENT_FAILURE)
    assert Notification.query.get(notification.id).status == NOTIFICATION_DELIVERED
    assert sample_job == Job.query.get(notification.job_id)


def test_should_update_status_by_id_if_created(sample_template, sample_notification):
    assert Notification.query.get(sample_notification.id).status == NOTIFICATION_CREATED
    updated = update_notification_status_by_id(sample_notification.id, NOTIFICATION_PERMANENT_FAILURE)
    assert Notification.query.get(sample_notification.id).status == NOTIFICATION_PERMANENT_FAILURE
    assert updated.status == NOTIFICATION_PERMANENT_FAILURE


def test_should_update_status_by_id_if_pending_virus_check(sample_letter_template):
    notification = create_notification(template=sample_letter_template, status=NOTIFICATION_PENDING_VIRUS_CHECK)
    assert Notification.query.get(notification.id).status == NOTIFICATION_PENDING_VIRUS_CHECK
    updated = update_notification_status_by_id(notification.id, NOTIFICATION_PERMANENT_FAILURE)
    assert Notification.query.get(notification.id).status == NOTIFICATION_PERMANENT_FAILURE
    assert updated.status == NOTIFICATION_PERMANENT_FAILURE


def test_should_update_status_by_id_and_set_sent_by(sample_template):
    notification = create_notification(template=sample_template, status='sending')

    updated = update_notification_status_by_id(notification.id, 'delivered', sent_by='mmg')
    assert updated.status == 'delivered'
    assert updated.sent_by == 'mmg'


def test_should_not_update_status_by_reference_if_from_country_with_no_delivery_receipts(sample_template):
    notification = create_notification(
        sample_template,
        status=NOTIFICATION_DELIVERED,
        reference='foo'
    )

    response = update_notification_status_by_reference('foo', 'failed')

    assert response is None
    assert notification.status == NOTIFICATION_DELIVERED


def test_should_not_update_status_by_id_if_sent_to_country_with_unknown_delivery_receipts(sample_template):
    notification = create_notification(
        sample_template,
        status=NOTIFICATION_SENT,
        international=True,
        phone_prefix='249'  # sudan has no delivery receipts (or at least, that we know about)
    )

    res = update_notification_status_by_id(notification.id, 'delivered')

    assert res is None
    assert notification.status == NOTIFICATION_SENT


def test_should_not_update_status_by_id_if_sent_to_country_with_carrier_delivery_receipts(sample_template):
    notification = create_notification(
        sample_template,
        status=NOTIFICATION_SENT,
        international=True,
        phone_prefix='1'  # americans only have carrier delivery receipts
    )

    res = update_notification_status_by_id(notification.id, 'delivered')

    assert res is None
    assert notification.status == NOTIFICATION_SENT


def test_should_not_update_status_by_id_if_sent_to_country_with_delivery_receipts(sample_template):
    notification = create_notification(
        sample_template,
        status=NOTIFICATION_SENT,
        international=True,
        phone_prefix='7'  # russians have full delivery receipts
    )

    res = update_notification_status_by_id(notification.id, 'delivered')

    assert res == notification
    assert notification.status == NOTIFICATION_DELIVERED


def test_should_not_update_status_by_reference_if_not_sending(sample_template):
    notification = create_notification(template=sample_template, status=NOTIFICATION_CREATED, reference='reference')
    assert Notification.query.get(notification.id).status == NOTIFICATION_CREATED
    updated = update_notification_status_by_reference('reference', NOTIFICATION_PERMANENT_FAILURE)
    assert Notification.query.get(notification.id).status == NOTIFICATION_CREATED
    assert not updated


def test_should_by_able_to_update_status_by_id_from_pending_to_delivered(sample_template, sample_job):
    notification = create_notification(template=sample_template, job=sample_job, status='sending')

    assert update_notification_status_by_id(notification_id=notification.id, status='pending')
    assert Notification.query.get(notification.id).status == 'pending'

    assert update_notification_status_by_id(notification.id, 'delivered')
    assert Notification.query.get(notification.id).status == 'delivered'


def test_should_by_able_to_update_status_by_id_from_pending_to_temporary_failure(sample_template, sample_job):
    notification = create_notification(template=sample_template, job=sample_job, status='sending')

    assert update_notification_status_by_id(notification_id=notification.id, status='pending')
    assert Notification.query.get(notification.id).status == 'pending'

    assert update_notification_status_by_id(notification.id, status='permanent-failure')

    assert Notification.query.get(notification.id).status == 'temporary-failure'


def test_should_by_able_to_update_status_by_id_from_sending_to_permanent_failure(sample_template, sample_job):
    data = _notification_json(sample_template, job_id=sample_job.id, status='sending')
    notification = Notification(**data)
    dao_create_notification(notification)
    assert Notification.query.get(notification.id).status == 'sending'

    assert update_notification_status_by_id(
        notification.id,
        status='permanent-failure'
    )
    assert Notification.query.get(notification.id).status == 'permanent-failure'


def test_should_not_update_status_once_notification_status_is_delivered(
        sample_email_template):
    notification = create_notification(template=sample_email_template, status='sending')
    assert Notification.query.get(notification.id).status == "sending"

    notification.reference = 'reference'
    dao_update_notification(notification)
    update_notification_status_by_reference('reference', 'delivered')
    assert Notification.query.get(notification.id).status == 'delivered'

    update_notification_status_by_reference('reference', 'failed')
    assert Notification.query.get(notification.id).status == 'delivered'


def test_should_return_zero_count_if_no_notification_with_id():
    assert not update_notification_status_by_id(str(uuid.uuid4()), 'delivered')


def test_should_return_zero_count_if_no_notification_with_reference():
    assert not update_notification_status_by_reference('something', 'delivered')


def test_create_notification_creates_notification_with_personalisation(sample_template_with_placeholders,
                                                                       sample_job):
    assert Notification.query.count() == 0

    data = create_notification(template=sample_template_with_placeholders,
                               job=sample_job,
                               personalisation={'name': 'Jo'},
                               status='created')

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data.to == notification_from_db.to
    assert data.job_id == notification_from_db.job_id
    assert data.service == notification_from_db.service
    assert data.template == notification_from_db.template
    assert data.template_version == notification_from_db.template_version
    assert data.created_at == notification_from_db.created_at
    assert notification_from_db.status == 'created'
    assert {'name': 'Jo'} == notification_from_db.personalisation


def test_save_notification_creates_sms(sample_template, sample_job):
    assert Notification.query.count() == 0

    data = _notification_json(sample_template, job_id=sample_job.id)

    notification = Notification(**data)
    dao_create_notification(notification)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data['to'] == notification_from_db.to
    assert data['job_id'] == notification_from_db.job_id
    assert data['service'] == notification_from_db.service
    assert data['template_id'] == notification_from_db.template_id
    assert data['template_version'] == notification_from_db.template_version
    assert data['created_at'] == notification_from_db.created_at
    assert notification_from_db.status == 'created'


def test_save_notification_and_create_email(sample_email_template, sample_job):
    assert Notification.query.count() == 0

    data = _notification_json(sample_email_template, job_id=sample_job.id)

    notification = Notification(**data)
    dao_create_notification(notification)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data['to'] == notification_from_db.to
    assert data['job_id'] == notification_from_db.job_id
    assert data['service'] == notification_from_db.service
    assert data['template_id'] == notification_from_db.template_id
    assert data['template_version'] == notification_from_db.template_version
    assert data['created_at'] == notification_from_db.created_at
    assert notification_from_db.status == 'created'


def test_save_notification(sample_email_template, sample_job):
    assert Notification.query.count() == 0
    data = _notification_json(sample_email_template, job_id=sample_job.id)

    notification_1 = Notification(**data)
    notification_2 = Notification(**data)
    dao_create_notification(notification_1)

    assert Notification.query.count() == 1

    dao_create_notification(notification_2)

    assert Notification.query.count() == 2


def test_save_notification_does_not_creates_history(sample_email_template, sample_job):
    assert Notification.query.count() == 0
    data = _notification_json(sample_email_template, job_id=sample_job.id)

    notification_1 = Notification(**data)
    dao_create_notification(notification_1)

    assert Notification.query.count() == 1
    assert NotificationHistory.query.count() == 0


def test_update_notification_with_research_mode_service_does_not_create_or_update_history(
        sample_template):
    sample_template.service.research_mode = True
    notification = create_notification(template=sample_template)

    assert Notification.query.count() == 1
    assert NotificationHistory.query.count() == 0

    notification.status = 'delivered'
    dao_update_notification(notification)

    assert Notification.query.one().status == 'delivered'
    assert NotificationHistory.query.count() == 0


def test_not_save_notification_and_not_create_stats_on_commit_error(sample_template, sample_job, mmg_provider):
    random_id = str(uuid.uuid4())

    assert Notification.query.count() == 0
    data = _notification_json(sample_template, job_id=random_id)

    notification = Notification(**data)
    with pytest.raises(SQLAlchemyError):
        dao_create_notification(notification)

    assert Notification.query.count() == 0
    assert Job.query.get(sample_job.id).notifications_sent == 0


def test_save_notification_and_increment_job(sample_template, sample_job, mmg_provider):
    assert Notification.query.count() == 0
    data = _notification_json(sample_template, job_id=sample_job.id)

    notification = Notification(**data)
    dao_create_notification(notification)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data['to'] == notification_from_db.to
    assert data['job_id'] == notification_from_db.job_id
    assert data['service'] == notification_from_db.service
    assert data['template_id'] == notification_from_db.template_id
    assert data['template_version'] == notification_from_db.template_version
    assert data['created_at'] == notification_from_db.created_at
    assert notification_from_db.status == 'created'

    notification_2 = Notification(**data)
    dao_create_notification(notification_2)
    assert Notification.query.count() == 2


def test_save_notification_and_increment_correct_job(notify_db, notify_db_session, sample_template, mmg_provider):
    job_1 = create_job(sample_template)
    job_2 = create_job(sample_template)

    assert Notification.query.count() == 0
    data = _notification_json(sample_template, job_id=job_1.id)

    notification = Notification(**data)
    dao_create_notification(notification)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data['to'] == notification_from_db.to
    assert data['job_id'] == notification_from_db.job_id
    assert data['service'] == notification_from_db.service
    assert data['template_id'] == notification_from_db.template_id
    assert data['template_version'] == notification_from_db.template_version
    assert data['created_at'] == notification_from_db.created_at
    assert notification_from_db.status == 'created'
    assert job_1.id != job_2.id


def test_save_notification_with_no_job(sample_template, mmg_provider):
    assert Notification.query.count() == 0
    data = _notification_json(sample_template)

    notification = Notification(**data)
    dao_create_notification(notification)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data['to'] == notification_from_db.to
    assert data['service'] == notification_from_db.service
    assert data['template_id'] == notification_from_db.template_id
    assert data['template_version'] == notification_from_db.template_version
    assert data['created_at'] == notification_from_db.created_at
    assert notification_from_db.status == 'created'


def test_get_notification_with_personalisation_by_id(sample_template):
    notification = create_notification(template=sample_template,
                                       scheduled_for='2017-05-05 14:15',
                                       status='created')
    notification_from_db = get_notification_with_personalisation(
        sample_template.service.id,
        notification.id,
        key_type=None
    )
    assert notification == notification_from_db
    assert notification_from_db.scheduled_notification.scheduled_for == datetime(2017, 5, 5, 14, 15)


def test_get_notification_by_id_when_notification_exists(sample_notification):
    notification_from_db = get_notification_by_id(sample_notification.id)

    assert sample_notification == notification_from_db


def test_get_notification_by_id_when_notification_does_not_exist(notify_db, fake_uuid):
    notification_from_db = get_notification_by_id(fake_uuid)

    assert notification_from_db is None


def test_get_notification_by_id_when_notification_exists_for_different_service(sample_notification):
    another_service = create_service(service_name='Another service')

    with pytest.raises(NoResultFound):
        get_notification_by_id(sample_notification.id, another_service.id, _raise=True)


def test_get_notifications_by_reference(sample_template):
    client_reference = 'some-client-ref'
    assert len(Notification.query.all()) == 0
    create_notification(sample_template, client_reference=client_reference)
    create_notification(sample_template, client_reference=client_reference)
    create_notification(sample_template, client_reference='other-ref')
    all_notifications = get_notifications_for_service(
        sample_template.service_id,
        client_reference=client_reference
    ).items
    assert len(all_notifications) == 2


def test_save_notification_no_job_id(sample_template):
    assert Notification.query.count() == 0
    data = _notification_json(sample_template)

    notification = Notification(**data)
    dao_create_notification(notification)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data['to'] == notification_from_db.to
    assert data['service'] == notification_from_db.service
    assert data['template_id'] == notification_from_db.template_id
    assert data['template_version'] == notification_from_db.template_version
    assert notification_from_db.status == 'created'
    assert data.get('job_id') is None


def test_get_notification_for_job(sample_notification):
    notification_from_db = get_notification_for_job(
        sample_notification.service.id,
        sample_notification.job_id,
        sample_notification.id)
    assert sample_notification == notification_from_db


def test_get_all_notifications_for_job(sample_job):
    for i in range(0, 5):
        try:
            create_notification(template=sample_job.template, job=sample_job)
        except IntegrityError:
            pass

    notifications_from_db = get_notifications_for_job(sample_job.service.id, sample_job.id).items
    assert len(notifications_from_db) == 5


def test_get_all_notifications_for_job_by_status(sample_job):
    notifications = partial(get_notifications_for_job, sample_job.service.id, sample_job.id)

    for status in NOTIFICATION_STATUS_TYPES:
        create_notification(
            template=sample_job.template,
            job=sample_job,
            status=status
        )

    assert len(notifications().items) == len(NOTIFICATION_STATUS_TYPES)

    for status in NOTIFICATION_STATUS_TYPES:
        if status == 'failed':
            assert len(notifications(filter_dict={'status': status}).items) == len(NOTIFICATION_STATUS_TYPES_FAILED)
        else:
            assert len(notifications(filter_dict={'status': status}).items) == 1

    assert len(notifications(filter_dict={'status': NOTIFICATION_STATUS_TYPES[:3]}).items) == 3


def test_update_notification_sets_status(sample_notification):
    assert sample_notification.status == 'created'
    sample_notification.status = 'failed'
    dao_update_notification(sample_notification)
    notification_from_db = Notification.query.get(sample_notification.id)
    assert notification_from_db.status == 'failed'


@freeze_time("2016-01-10")
# This test assumes the local timezone is EST
def test_should_limit_notifications_return_by_day_limit_plus_one(sample_template):
    assert len(Notification.query.all()) == 0

    # create one notification a day between 1st and 9th
    for i in range(1, 11):
        past_date = '2016-01-{0:02d} 12:00:00'.format(i)
        with freeze_time(past_date):
            create_notification(sample_template, created_at=datetime.utcnow(), status="failed")

    all_notifications = Notification.query.all()
    assert len(all_notifications) == 10

    all_notifications = get_notifications_for_service(sample_template.service_id, limit_days=10).items
    assert len(all_notifications) == 10

    all_notifications = get_notifications_for_service(sample_template.service_id, limit_days=1).items
    assert len(all_notifications) == 2


def test_creating_notification_does_not_add_notification_history(sample_template):
    create_notification(template=sample_template)
    assert Notification.query.count() == 1
    assert NotificationHistory.query.count() == 0


def test_should_delete_notification_for_id(sample_template):
    notification = create_notification(template=sample_template)

    assert Notification.query.count() == 1
    assert NotificationHistory.query.count() == 0

    dao_delete_notification_by_id(notification.id)

    assert Notification.query.count() == 0


def test_should_delete_recipient_identifiers_if_notification_deleted(
        notify_db,
        sample_job,
        sample_api_key,
        mocker
):
    mocker.patch(
        'app.notifications.process_notifications.accept_recipient_identifiers_enabled',
        return_value=True
    )
    recipient_identifier = {'id_type': IdentifierType.VA_PROFILE_ID.value, 'id_value': 'foo'}
    notification = persist_notification(
        template_id=sample_job.template.id,
        template_version=sample_job.template.version,
        service=sample_job.service,
        personalisation=None,
        notification_type=EMAIL_TYPE,
        api_key_id=sample_api_key.id,
        key_type=sample_api_key.key_type,
        job_id=sample_job.id,
        recipient_identifier=recipient_identifier
    )
    assert RecipientIdentifier.query.get(
        (notification.id, recipient_identifier['id_type'], recipient_identifier['id_value'])) \
        .notification_id == notification.id

    dao_delete_notification_by_id(notification.id)

    assert Notification.query.get(notification.id) is None
    assert RecipientIdentifier.query.get(
        (notification.id, recipient_identifier['id_type'], recipient_identifier['id_value'])) is None


def test_should_delete_notification_and_ignore_history_for_research_mode(sample_template):
    sample_template.service.research_mode = True

    notification = create_notification(template=sample_template)

    assert Notification.query.count() == 1

    dao_delete_notification_by_id(notification.id)

    assert Notification.query.count() == 0


def test_should_delete_only_notification_with_id(sample_template):
    notification_1 = create_notification(template=sample_template)
    notification_2 = create_notification(template=sample_template)
    assert Notification.query.count() == 2

    dao_delete_notification_by_id(notification_1.id)

    assert Notification.query.count() == 1
    assert Notification.query.first().id == notification_2.id


def test_should_delete_no_notifications_if_no_matching_ids(
        sample_template
):
    create_notification(template=sample_template)
    assert Notification.query.count() == 1

    dao_delete_notification_by_id(uuid.uuid4())

    assert Notification.query.count() == 1


def _notification_json(sample_template, job_id=None, id=None, status=None):
    data = {
        'to': '+44709123456',
        'service': sample_template.service,
        'service_id': sample_template.service.id,
        'template_id': sample_template.id,
        'template_version': sample_template.version,
        'created_at': datetime.utcnow(),
        'billable_units': 1,
        'notification_type': sample_template.template_type,
        'key_type': KEY_TYPE_NORMAL
    }
    if job_id:
        data.update({'job_id': job_id})
    if id:
        data.update({'id': id})
    if status:
        data.update({'status': status})
    return data


def test_dao_timeout_notifications(sample_template):
    with freeze_time(datetime.utcnow() - timedelta(minutes=2)):
        created = create_notification(sample_template, status='created')
        sending = create_notification(sample_template, status='sending')
        pending = create_notification(sample_template, status='pending')
        delivered = create_notification(sample_template, status='delivered')

    assert Notification.query.get(created.id).status == 'created'
    assert Notification.query.get(sending.id).status == 'sending'
    assert Notification.query.get(pending.id).status == 'pending'
    assert Notification.query.get(delivered.id).status == 'delivered'
    technical_failure_notifications, temporary_failure_notifications = dao_timeout_notifications(1)
    assert Notification.query.get(created.id).status == 'technical-failure'
    assert Notification.query.get(sending.id).status == 'temporary-failure'
    assert Notification.query.get(pending.id).status == 'temporary-failure'
    assert Notification.query.get(delivered.id).status == 'delivered'
    assert len(technical_failure_notifications + temporary_failure_notifications) == 3


def test_dao_timeout_notifications_only_updates_for_older_notifications(sample_template):
    with freeze_time(datetime.utcnow() + timedelta(minutes=10)):
        created = create_notification(sample_template, status='created')
        sending = create_notification(sample_template, status='sending')
        pending = create_notification(sample_template, status='pending')
        delivered = create_notification(sample_template, status='delivered')

    assert Notification.query.get(created.id).status == 'created'
    assert Notification.query.get(sending.id).status == 'sending'
    assert Notification.query.get(pending.id).status == 'pending'
    assert Notification.query.get(delivered.id).status == 'delivered'
    technical_failure_notifications, temporary_failure_notifications = dao_timeout_notifications(1)
    assert len(technical_failure_notifications + temporary_failure_notifications) == 0


def test_dao_timeout_notifications_doesnt_affect_letters(sample_letter_template):
    with freeze_time(datetime.utcnow() - timedelta(minutes=2)):
        created = create_notification(sample_letter_template, status='created')
        sending = create_notification(sample_letter_template, status='sending')
        pending = create_notification(sample_letter_template, status='pending')
        delivered = create_notification(sample_letter_template, status='delivered')

    assert Notification.query.get(created.id).status == 'created'
    assert Notification.query.get(sending.id).status == 'sending'
    assert Notification.query.get(pending.id).status == 'pending'
    assert Notification.query.get(delivered.id).status == 'delivered'

    technical_failure_notifications, temporary_failure_notifications = dao_timeout_notifications(1)


def test_should_return_notifications_excluding_jobs_by_default(sample_template, sample_job, sample_api_key):
    create_notification(sample_template, job=sample_job)
    without_job = create_notification(sample_template, api_key=sample_api_key)

    include_jobs = get_notifications_for_service(sample_template.service_id, include_jobs=True).items
    assert len(include_jobs) == 2

    exclude_jobs_by_default = get_notifications_for_service(sample_template.service_id).items
    assert len(exclude_jobs_by_default) == 1
    assert exclude_jobs_by_default[0].id == without_job.id

    exclude_jobs_manually = get_notifications_for_service(sample_template.service_id, include_jobs=False).items
    assert len(exclude_jobs_manually) == 1
    assert exclude_jobs_manually[0].id == without_job.id


def test_should_return_notifications_including_one_offs_by_default(sample_user, sample_template):
    create_notification(sample_template, one_off=True, created_by_id=sample_user.id)
    not_one_off = create_notification(sample_template)

    exclude_one_offs = get_notifications_for_service(sample_template.service_id, include_one_off=False).items
    assert len(exclude_one_offs) == 1
    assert exclude_one_offs[0].id == not_one_off.id

    include_one_offs_manually = get_notifications_for_service(sample_template.service_id, include_one_off=True).items
    assert len(include_one_offs_manually) == 2

    include_one_offs_by_default = get_notifications_for_service(sample_template.service_id).items
    assert len(include_one_offs_by_default) == 2


def test_should_not_count_pages_when_given_a_flag(sample_user, sample_template):
    create_notification(sample_template)
    notification = create_notification(sample_template)

    pagination = get_notifications_for_service(sample_template.service_id, count_pages=False, page_size=1)
    assert len(pagination.items) == 1
    assert pagination.total is None
    assert pagination.items[0].id == notification.id


def test_get_notifications_created_by_api_or_csv_are_returned_correctly_excluding_test_key_notifications(
        notify_db,
        notify_db_session,
        sample_service,
        sample_job,
        sample_api_key,
        sample_team_api_key,
        sample_test_api_key
):
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), job=sample_job
    )
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), api_key=sample_api_key,
        key_type=sample_api_key.key_type
    )
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), api_key=sample_team_api_key,
        key_type=sample_team_api_key.key_type
    )
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), api_key=sample_test_api_key,
        key_type=sample_test_api_key.key_type
    )

    all_notifications = Notification.query.all()
    assert len(all_notifications) == 4

    # returns all real API derived notifications
    all_notifications = get_notifications_for_service(sample_service.id).items
    assert len(all_notifications) == 2

    # returns all API derived notifications, including those created with test key
    all_notifications = get_notifications_for_service(sample_service.id, include_from_test_key=True).items
    assert len(all_notifications) == 3

    # all real notifications including jobs
    all_notifications = get_notifications_for_service(sample_service.id, limit_days=1, include_jobs=True).items
    assert len(all_notifications) == 3


def test_get_notifications_with_a_live_api_key_type(
        sample_job,
        sample_api_key,
        sample_team_api_key,
        sample_test_api_key
):
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), job=sample_job
    )
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), api_key=sample_api_key,
        key_type=sample_api_key.key_type
    )
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), api_key=sample_team_api_key,
        key_type=sample_team_api_key.key_type
    )
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), api_key=sample_test_api_key,
        key_type=sample_test_api_key.key_type
    )

    all_notifications = Notification.query.all()
    assert len(all_notifications) == 4

    # only those created with normal API key, no jobs
    all_notifications = get_notifications_for_service(
        sample_job.service.id, limit_days=1, key_type=KEY_TYPE_NORMAL
    ).items
    assert len(all_notifications) == 1

    # only those created with normal API key, with jobs
    all_notifications = get_notifications_for_service(
        sample_job.service.id, limit_days=1, include_jobs=True, key_type=KEY_TYPE_NORMAL
    ).items
    assert len(all_notifications) == 2


def test_get_notifications_with_a_test_api_key_type(
        sample_job,
        sample_api_key,
        sample_team_api_key,
        sample_test_api_key
):
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), job=sample_job
    )
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), api_key=sample_api_key,
        key_type=sample_api_key.key_type
    )
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), api_key=sample_team_api_key,
        key_type=sample_team_api_key.key_type
    )
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), api_key=sample_test_api_key,
        key_type=sample_test_api_key.key_type
    )

    # only those created with test API key, no jobs
    all_notifications = get_notifications_for_service(sample_job.service_id, limit_days=1, key_type=KEY_TYPE_TEST).items
    assert len(all_notifications) == 1

    # only those created with test API key, no jobs, even when requested
    all_notifications = get_notifications_for_service(sample_job.service_id, limit_days=1, include_jobs=True,
                                                      key_type=KEY_TYPE_TEST).items
    assert len(all_notifications) == 1


def test_get_notifications_with_a_team_api_key_type(
        sample_job,
        sample_api_key,
        sample_team_api_key,
        sample_test_api_key
):
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), job=sample_job
    )
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), api_key=sample_api_key,
        key_type=sample_api_key.key_type
    )
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), api_key=sample_team_api_key,
        key_type=sample_team_api_key.key_type
    )
    create_notification(
        sample_job.template, created_at=datetime.utcnow(), api_key=sample_test_api_key,
        key_type=sample_test_api_key.key_type
    )

    # only those created with team API key, no jobs
    all_notifications = get_notifications_for_service(sample_job.service_id, limit_days=1, key_type=KEY_TYPE_TEAM).items
    assert len(all_notifications) == 1

    # only those created with team API key, no jobs, even when requested
    all_notifications = get_notifications_for_service(sample_job.service_id, limit_days=1, include_jobs=True,
                                                      key_type=KEY_TYPE_TEAM).items
    assert len(all_notifications) == 1


def test_should_exclude_test_key_notifications_by_default(
        sample_job,
        sample_api_key,
        sample_team_api_key,
        sample_test_api_key
):
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), job=sample_job
    )

    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), api_key=sample_api_key,
        key_type=sample_api_key.key_type
    )
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), api_key=sample_team_api_key,
        key_type=sample_team_api_key.key_type
    )
    create_notification(
        template=sample_job.template, created_at=datetime.utcnow(), api_key=sample_test_api_key,
        key_type=sample_test_api_key.key_type
    )

    all_notifications = Notification.query.all()
    assert len(all_notifications) == 4

    all_notifications = get_notifications_for_service(sample_job.service_id, limit_days=1).items
    assert len(all_notifications) == 2

    all_notifications = get_notifications_for_service(sample_job.service_id, limit_days=1, include_jobs=True).items
    assert len(all_notifications) == 3

    all_notifications = get_notifications_for_service(sample_job.service_id, limit_days=1, key_type=KEY_TYPE_TEST).items
    assert len(all_notifications) == 1


@pytest.mark.parametrize(
    "normal_sending,slow_sending,normal_delivered,slow_delivered,threshold,expected_result",
    [
        (0, 0, 0, 0, 0.1, False),
        (1, 0, 0, 0, 0.1, False),
        (1, 1, 0, 0, 0.1, True),
        (0, 0, 1, 1, 0.1, True),
        (1, 1, 1, 1, 0.5, True),
        (1, 1, 1, 1, 0.6, False),
        (45, 5, 45, 5, 0.1, True),
    ]
)
@freeze_time("2018-12-04 12:00:00.000000")
def test_is_delivery_slow_for_provider(
    notify_db_session,
    sample_template,
    normal_sending,
    slow_sending,
    normal_delivered,
    slow_delivered,
    threshold,
    expected_result
):
    normal_notification = partial(
        create_notification,
        template=sample_template,
        sent_by='mmg',
        sent_at=datetime.now(),
        updated_at=datetime.now()
    )

    slow_notification = partial(
        create_notification,
        template=sample_template,
        sent_by='mmg',
        sent_at=datetime.now() - timedelta(minutes=5),
        updated_at=datetime.now()
    )

    for _ in range(normal_sending):
        normal_notification(status='sending')
    for _ in range(slow_sending):
        slow_notification(status='sending')
    for _ in range(normal_delivered):
        normal_notification(status='delivered')
    for _ in range(slow_delivered):
        slow_notification(status='delivered')

    assert is_delivery_slow_for_provider(datetime.utcnow(), "mmg", threshold, timedelta(minutes=4)) is expected_result


@pytest.mark.parametrize("options,expected_result", [
    ({"status": NOTIFICATION_DELIVERED, "sent_by": "mmg"}, True),
    ({"status": NOTIFICATION_PENDING, "sent_by": "mmg"}, True),
    ({"status": NOTIFICATION_SENDING, "sent_by": "mmg"}, True),

    ({"status": NOTIFICATION_TEMPORARY_FAILURE, "sent_by": "mmg"}, False),
    ({"status": NOTIFICATION_DELIVERED, "sent_by": "mmg", "sent_at": None}, False),
    ({"status": NOTIFICATION_DELIVERED, "sent_by": "mmg", "key_type": KEY_TYPE_TEST}, False),
    ({"status": NOTIFICATION_SENDING, "sent_by": "firetext"}, False),
    ({"status": NOTIFICATION_DELIVERED, "sent_by": "firetext"}, False),

])
@freeze_time("2018-12-04 12:00:00.000000")
def test_delivery_is_delivery_slow_for_provider_filters_out_notifications_it_should_not_count(
    notify_db_session,
    sample_template,
    options,
    expected_result
):
    create_notification_with = {
        "template": sample_template,
        "sent_at": datetime.now() - timedelta(minutes=5),
        "updated_at": datetime.now(),
    }
    create_notification_with.update(options)
    create_notification(
        **create_notification_with
    )
    assert is_delivery_slow_for_provider(datetime.utcnow(), "mmg", 0.1, timedelta(minutes=4)) is expected_result


def test_dao_get_notifications_by_to_field(sample_template):

    recipient_to_search_for = {
        'to_field': '+16502532222',
        'normalised_to': '+16502532222'
    }

    notification1 = create_notification(
        template=sample_template, **recipient_to_search_for
    )
    create_notification(
        template=sample_template, key_type=KEY_TYPE_TEST, **recipient_to_search_for
    )
    create_notification(
        template=sample_template, to_field='jack@gmail.com', normalised_to='jack@gmail.com'
    )
    create_notification(
        template=sample_template, to_field='jane@gmail.com', normalised_to='jane@gmail.com'
    )

    results = dao_get_notifications_by_to_field(
        notification1.service_id,
        recipient_to_search_for["to_field"],
        notification_type=SMS_TYPE
    )

    assert len(results) == 1
    assert notification1.id == results[0].id


@pytest.mark.parametrize("search_term",
                         ["JACK", "JACK@gmail.com", "jack@gmail.com"])
def test_dao_get_notifications_by_to_field_search_is_not_case_sensitive(sample_email_template, search_term):
    notification = create_notification(
        template=sample_email_template, to_field='jack@gmail.com', normalised_to='jack@gmail.com'
    )
    results = dao_get_notifications_by_to_field(notification.service_id, search_term, notification_type=EMAIL_TYPE)
    notification_ids = [notification.id for notification in results]

    assert len(results) == 1
    assert notification.id in notification_ids


def test_dao_get_notifications_by_to_field_matches_partial_emails(sample_email_template):
    notification_1 = create_notification(
        template=sample_email_template, to_field='jack@gmail.com', normalised_to='jack@gmail.com'
    )
    notification_2 = create_notification(
        template=sample_email_template, to_field='jacque@gmail.com', normalised_to='jacque@gmail.com'
    )
    results = dao_get_notifications_by_to_field(notification_1.service_id, 'ack', notification_type=EMAIL_TYPE)
    notification_ids = [notification.id for notification in results]

    assert len(results) == 1
    assert notification_1.id in notification_ids
    assert notification_2.id not in notification_ids


@pytest.mark.parametrize('search_term, expected_result_count', [
    ('foobar', 1),
    ('foo', 2),
    ('bar', 2),
    ('foo%', 1),
    ('%%bar', 1),
    ('%_', 1),
    ('%', 2),
    ('_', 1),
    ('/', 1),
    ('\\', 1),
    ('baz\\baz', 1),
    ('%foo', 0),
    ('%_%', 0),
    ('example.com', 5),
])
def test_dao_get_notifications_by_to_field_escapes(
    sample_email_template,
    search_term,
    expected_result_count,
):

    for email_address in {
        'foo%_@example.com',
        '%%bar@example.com',
        'foobar@example.com',
        '/@example.com',
        'baz\\baz@example.com',
    }:
        create_notification(
            template=sample_email_template,
            to_field=email_address,
            normalised_to=email_address,
        )

    assert len(dao_get_notifications_by_to_field(
        sample_email_template.service_id,
        search_term,
        notification_type=EMAIL_TYPE,
    )) == expected_result_count


@pytest.mark.parametrize('search_term', [
    '100',
    '09001',
    '077009001',
    '07700 9001',
    '(0)7700 9001',
    '4477009001',
    '+4477009001',
    pytest.param('+44077009001', marks=pytest.mark.skip(reason='No easy way to normalise this')),
    pytest.param('+44(0)77009001', marks=pytest.mark.skip(reason='No easy way to normalise this')),
])
def test_dao_get_notifications_by_to_field_matches_partial_phone_numbers(
    sample_template,
    search_term,
):
    assert sample_template.template_type == SMS_TYPE, "This should be the default value."

    notification_1 = create_notification(
        template=sample_template,
        to_field='+447700900100',
        normalised_to='1447700900100',
    )
    assert notification_1.notification_type == SMS_TYPE

    notification_2 = create_notification(
        template=sample_template,
        to_field='+447700900200',
        normalised_to='1447700900200',
    )
    assert notification_2.notification_type == SMS_TYPE

    results = dao_get_notifications_by_to_field(notification_1.service_id, search_term, notification_type=SMS_TYPE)
    notification_ids = [notification.id for notification in results]

    assert len(results) == 1
    assert notification_1.id in notification_ids
    assert notification_2.id not in notification_ids


@pytest.mark.parametrize('to', [
    'not@email', '123'
])
def test_dao_get_notifications_by_to_field_accepts_invalid_phone_numbers_and_email_addresses(
    sample_template,
    to,
):
    notification = create_notification(
        template=sample_template, to_field='test@example.com', normalised_to='test@example.com'
    )
    results = dao_get_notifications_by_to_field(notification.service_id, to, notification_type=EMAIL_TYPE)
    assert len(results) == 0


def test_dao_get_notifications_by_to_field_search_ignores_spaces(sample_template):
    notification1 = create_notification(
        template=sample_template, to_field='+16502532222', normalised_to='+16502532222'
    )
    notification2 = create_notification(
        template=sample_template, to_field='+1 650 253 2222', normalised_to='+16502532222'
    )
    notification3 = create_notification(
        template=sample_template, to_field=' +1650253 2 222', normalised_to='+16502532222'
    )
    create_notification(
        template=sample_template, to_field='jaCK@gmail.com', normalised_to='jack@gmail.com'
    )

    results = dao_get_notifications_by_to_field(notification1.service_id, '+16502532222', notification_type=SMS_TYPE)
    notification_ids = [notification.id for notification in results]

    assert len(results) == 3
    assert notification1.id in notification_ids
    assert notification2.id in notification_ids
    assert notification3.id in notification_ids


@pytest.mark.parametrize('phone_search', (
    '650', '502', '+16502532222'
))
@pytest.mark.parametrize('email_search', (
    'example', 'eXaMpLe',
))
def test_dao_get_notifications_by_to_field_only_searches_one_notification_type(
    notify_db_session,
    phone_search,
    email_search,
):
    service = create_service()
    sms_template = create_template(service=service)
    email_template = create_template(service=service, template_type=EMAIL_TYPE)
    sms = create_notification(template=sms_template, to_field='6502532222', normalised_to='+16502532222')
    email = create_notification(
        template=email_template, to_field='165@example.com', normalised_to='165@example.com'
    )
    results = dao_get_notifications_by_to_field(service.id, phone_search, notification_type=SMS_TYPE)
    assert len(results) == 1
    assert results[0].id == sms.id
    results = dao_get_notifications_by_to_field(service.id, phone_search)  # should assume SMS
    assert len(results) == 1
    assert results[0].id == sms.id
    results = dao_get_notifications_by_to_field(service.id, '165', notification_type=EMAIL_TYPE)
    assert len(results) == 1
    assert results[0].id == email.id
    results = dao_get_notifications_by_to_field(service.id, email_search)  # should assume email
    assert len(results) == 1
    assert results[0].id == email.id


def test_dao_created_scheduled_notification(sample_notification):

    scheduled_notification = ScheduledNotification(notification_id=sample_notification.id,
                                                   scheduled_for=datetime.strptime("2017-01-05 14:15",
                                                                                   "%Y-%m-%d %H:%M"))
    dao_created_scheduled_notification(scheduled_notification)
    saved_notification = ScheduledNotification.query.all()
    assert len(saved_notification) == 1
    assert saved_notification[0].notification_id == sample_notification.id
    assert saved_notification[0].scheduled_for == datetime(2017, 1, 5, 14, 15)


def test_dao_get_scheduled_notifications(sample_template):
    notification_1 = create_notification(template=sample_template, scheduled_for='2017-05-05 14:15',
                                         status='created')
    create_notification(template=sample_template, scheduled_for='2017-05-04 14:15', status='delivered')
    create_notification(template=sample_template, status='created')
    scheduled_notifications = dao_get_scheduled_notifications()
    assert len(scheduled_notifications) == 1
    assert scheduled_notifications[0].id == notification_1.id
    assert scheduled_notifications[0].scheduled_notification.pending


def test_set_scheduled_notification_to_processed(sample_template):
    notification_1 = create_notification(template=sample_template, scheduled_for='2017-05-05 14:15',
                                         status='created')
    scheduled_notifications = dao_get_scheduled_notifications()
    assert len(scheduled_notifications) == 1
    assert scheduled_notifications[0].id == notification_1.id
    assert scheduled_notifications[0].scheduled_notification.pending

    set_scheduled_notification_to_processed(notification_1.id)
    scheduled_notifications = dao_get_scheduled_notifications()
    assert not scheduled_notifications


def test_dao_get_notifications_by_to_field_filters_status(sample_template):
    notification = create_notification(
        template=sample_template, to_field='+16502532222',
        normalised_to='+16502532222', status='delivered'
    )
    create_notification(
        template=sample_template, to_field='+16502532222',
        normalised_to='+16502532222', status='temporary-failure'
    )

    notifications = dao_get_notifications_by_to_field(notification.service_id, "+16502532222",
                                                      statuses=['delivered'],
                                                      notification_type=SMS_TYPE)

    assert len(notifications) == 1
    assert notification.id == notifications[0].id


def test_dao_get_notifications_by_to_field_filters_multiple_statuses(sample_template):
    notification1 = create_notification(
        template=sample_template, to_field='+16502532222',
        normalised_to='+16502532222', status='delivered'
    )
    notification2 = create_notification(
        template=sample_template, to_field='+16502532222',
        normalised_to='+16502532222', status='sending'
    )

    notifications = dao_get_notifications_by_to_field(
        notification1.service_id, "+16502532222", statuses=['delivered', 'sending'], notification_type=SMS_TYPE
    )
    notification_ids = [notification.id for notification in notifications]

    assert len(notifications) == 2
    assert notification1.id in notification_ids
    assert notification2.id in notification_ids


def test_dao_get_notifications_by_to_field_returns_all_if_no_status_filter(sample_template):
    notification1 = create_notification(
        template=sample_template, to_field='+16502532222',
        normalised_to='+16502532222', status='delivered'
    )
    notification2 = create_notification(
        template=sample_template, to_field='+16502532222',
        normalised_to='+16502532222', status='temporary-failure'
    )

    notifications = dao_get_notifications_by_to_field(
        notification1.service_id, "+16502532222", notification_type=SMS_TYPE
    )
    notification_ids = [notification.id for notification in notifications]

    assert len(notifications) == 2
    assert notification1.id in notification_ids
    assert notification2.id in notification_ids


@freeze_time('2016-01-01 11:10:00')
def test_dao_get_notifications_by_to_field_orders_by_created_at_desc(sample_template):
    notification = partial(
        create_notification,
        template=sample_template,
        to_field='+16502532222',
        normalised_to='+16502532222'
    )

    notification_a_minute_ago = notification(created_at=datetime.utcnow() - timedelta(minutes=1))
    notification = notification(created_at=datetime.utcnow())

    notifications = dao_get_notifications_by_to_field(
        sample_template.service_id, '+16502532222', notification_type=SMS_TYPE
    )

    assert len(notifications) == 2
    assert notifications[0].id == notification.id
    assert notifications[1].id == notification_a_minute_ago.id


def test_dao_get_last_notification_added_for_job_id_valid_job_id(sample_template):
    job = create_job(template=sample_template, notification_count=10,
                     created_at=datetime.utcnow() - timedelta(hours=2),
                     scheduled_for=datetime.utcnow() - timedelta(minutes=31),
                     processing_started=datetime.utcnow() - timedelta(minutes=31),
                     job_status=JOB_STATUS_IN_PROGRESS)
    create_notification(sample_template, job, 0)
    create_notification(sample_template, job, 1)
    last = create_notification(sample_template, job, 2)

    assert dao_get_last_notification_added_for_job_id(job.id) == last


def test_dao_get_last_notification_added_for_job_id_no_notifications(sample_template):
    job = create_job(template=sample_template, notification_count=10,
                     created_at=datetime.utcnow() - timedelta(hours=2),
                     scheduled_for=datetime.utcnow() - timedelta(minutes=31),
                     processing_started=datetime.utcnow() - timedelta(minutes=31),
                     job_status=JOB_STATUS_IN_PROGRESS)

    assert dao_get_last_notification_added_for_job_id(job.id) is None


def test_dao_get_last_notification_added_for_job_id_no_job(sample_template, fake_uuid):

    assert dao_get_last_notification_added_for_job_id(fake_uuid) is None


def test_dao_update_notifications_by_reference_updated_notifications(sample_template):
    notification_1 = create_notification(template=sample_template, reference='ref1')
    notification_2 = create_notification(template=sample_template, reference='ref2')

    updated_count, updated_history_count = dao_update_notifications_by_reference(
        references=['ref1', 'ref2'],
        update_dict={
            "status": "delivered",
            "billable_units": 2
        }
    )
    assert updated_count == 2
    updated_1 = Notification.query.get(notification_1.id)
    assert updated_1.billable_units == 2
    assert updated_1.status == 'delivered'
    updated_2 = Notification.query.get(notification_2.id)
    assert updated_2.billable_units == 2
    assert updated_2.status == 'delivered'

    assert updated_history_count == 0


def test_dao_update_notifications_by_reference_updates_history_some_notifications_exist(sample_template):
    create_notification(template=sample_template, reference='ref1')
    create_notification_history(template=sample_template, reference='ref2')

    updated_count, updated_history_count = dao_update_notifications_by_reference(
        references=['ref1', 'ref2'],
        update_dict={
            "status": "delivered",
            "billable_units": 2
        }
    )
    assert updated_count == 1
    assert updated_history_count == 1


def test_dao_update_notifications_by_reference_updates_history_no_notifications_exist(sample_template):
    create_notification_history(template=sample_template, reference='ref1')
    create_notification_history(template=sample_template, reference='ref2')

    updated_count, updated_history_count = dao_update_notifications_by_reference(
        references=['ref1', 'ref2'],
        update_dict={
            "status": "delivered",
            "billable_units": 2
        }
    )
    assert updated_count == 0
    assert updated_history_count == 2


def test_dao_update_notifications_by_reference_returns_zero_when_no_notifications_to_update(notify_db):
    updated_count, updated_history_count = dao_update_notifications_by_reference(
        references=['ref'],
        update_dict={
            "status": "delivered",
            "billable_units": 2
        }
    )

    assert updated_count == 0
    assert updated_history_count == 0


def test_dao_update_notifications_by_reference_set_returned_letter_status(sample_letter_template):
    notification = create_notification(template=sample_letter_template, reference='ref')

    updated_count, updated_history_count = dao_update_notifications_by_reference(
        references=['ref'],
        update_dict={"status": "returned-letter"}
    )

    assert updated_count == 1
    assert updated_history_count == 0
    assert Notification.query.get(notification.id).status == 'returned-letter'


def test_dao_update_notifications_by_reference_updates_history_when_one_of_two_notifications_exists(
        sample_letter_template
):
    notification1 = create_notification_history(template=sample_letter_template, reference='ref1')
    notification2 = create_notification(template=sample_letter_template, reference='ref2')

    updated_count, updated_history_count = dao_update_notifications_by_reference(
        references=['ref1', 'ref2'],
        update_dict={"status": "returned-letter"}
    )

    assert updated_count == 1
    assert updated_history_count == 1
    assert Notification.query.get(notification2.id).status == 'returned-letter'
    assert NotificationHistory.query.get(notification1.id).status == 'returned-letter'


def test_dao_get_notification_by_reference_with_one_match_returns_notification(sample_letter_template, notify_db):
    create_notification(template=sample_letter_template, reference='REF1')
    notification = dao_get_notification_by_reference('REF1')

    assert notification.reference == 'REF1'


def test_dao_get_notification_by_reference_with_multiple_matches_raises_error(sample_letter_template, notify_db):
    create_notification(template=sample_letter_template, reference='REF1')
    create_notification(template=sample_letter_template, reference='REF1')

    with pytest.raises(SQLAlchemyError):
        dao_get_notification_by_reference('REF1')


def test_dao_get_notification_by_reference_with_no_matches_raises_error(notify_db):
    with pytest.raises(SQLAlchemyError):
        dao_get_notification_by_reference('REF1')


def test_dao_get_notifications_by_reference(sample_template):
    create_notification(template=sample_template, reference='noref')
    notification_1 = create_notification(template=sample_template, reference='ref')
    notification_2 = create_notification(template=sample_template, reference='ref')

    notifications = dao_get_notifications_by_references(['ref'])
    assert len(notifications) == 2
    assert notifications[0].id in [notification_1.id, notification_2.id]
    assert notifications[1].id in [notification_1.id, notification_2.id]


def test_dao_get_notification_history_by_reference_with_one_match_returns_notification(
        sample_letter_template
):
    create_notification(template=sample_letter_template, reference='REF1')
    notification = dao_get_notification_history_by_reference('REF1')

    assert notification.reference == 'REF1'


def test_dao_get_notification_history_by_reference_with_multiple_matches_raises_error(
        sample_letter_template
):
    create_notification(template=sample_letter_template, reference='REF1')
    create_notification(template=sample_letter_template, reference='REF1')

    with pytest.raises(SQLAlchemyError):
        dao_get_notification_history_by_reference('REF1')


def test_dao_get_notification_history_by_reference_with_no_matches_raises_error(notify_db):
    with pytest.raises(SQLAlchemyError):
        dao_get_notification_history_by_reference('REF1')


@pytest.mark.parametrize("notification_type", [LETTER_TYPE, EMAIL_TYPE, SMS_TYPE])
def test_notifications_not_yet_sent(sample_service, notification_type):
    # The notification cannot be older than this number of seconds.
    older_than = 4
    template = create_template(service=sample_service, template_type=notification_type)
    old_notification = create_notification(template=template,
                                           created_at=datetime.utcnow() - timedelta(seconds=older_than),
                                           status='created')
    create_notification(template=template,
                        created_at=datetime.utcnow() - timedelta(seconds=older_than),
                        status='sending')
    create_notification(template=template, created_at=datetime.utcnow(), status='created')

    results = notifications_not_yet_sent(older_than, notification_type)
    assert len(results) == 1
    assert results[0] == old_notification


@pytest.mark.parametrize("notification_type", [LETTER_TYPE, EMAIL_TYPE, SMS_TYPE])
def test_notifications_not_yet_sent_return_no_rows(sample_service, notification_type):
    # The notification cannot be older than this number of seconds.
    older_than = 5
    template = create_template(service=sample_service, template_type=notification_type)
    create_notification(template=template,
                        created_at=datetime.utcnow(),
                        status='created')
    create_notification(template=template,
                        created_at=datetime.utcnow(),
                        status='sending')
    create_notification(template=template, created_at=datetime.utcnow(), status='delivered')

    results = notifications_not_yet_sent(older_than, notification_type)
    assert len(results) == 0


def test_update_notification_status_updates_failure_reason(sample_job, mocker):
    mocker.patch('app.dao.notifications_dao.is_feature_enabled', return_value=True)
    notification = create_notification(
        template=sample_job.template, status=NOTIFICATION_SENT, reference='reference', job=sample_job
    )

    failure_message = 'some failure'
    updated_notification = update_notification_status_by_id(
        notification.id, NOTIFICATION_PERMANENT_FAILURE, status_reason=failure_message
    )

    assert updated_notification.status_reason == failure_message


@pytest.mark.parametrize("next_status", [
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_SENDING,
    NOTIFICATION_PENDING,
    NOTIFICATION_SENT
])
def test_update_notification_status_by_id_cannot_exit(
        sample_template,
        next_status
):
    reference = str(uuid.uuid4())

    # create notification object
    create_notification(
        sample_template,
        reference=reference,
        sent_at=datetime.now()
    )

    # get the notification object
    notification = dao_get_notification_by_reference(reference)

    # check the values that attempt_to_get_notification() return against what we sent
    assert isinstance(notification, Notification)
    assert notification.status == NOTIFICATION_CREATED

    # assume you enter delivered state immediately after creation
    update_notification_status_by_id(
        notification_id=notification.id,
        status=NOTIFICATION_DELIVERED,
        current_status=NOTIFICATION_CREATED
    )

    # record the last update value that is in the database
    notification_last_updated = notification.updated_at

    # get the notification object and make sure it has the values you gave it
    notification = dao_get_notification_by_reference(reference)
    assert isinstance(notification, Notification)
    assert notification.status == NOTIFICATION_DELIVERED

    update_notification_status_by_id(
        notification_id=notification.id,
        status=next_status,
        current_status=NOTIFICATION_DELIVERED
    )

    notification = dao_get_notification_by_reference(reference)
    assert notification.updated_at == notification_last_updated
    assert notification.status == NOTIFICATION_DELIVERED

    update_notification_status_by_id(
        notification_id=notification.id,
        status=next_status
    )

    notification = dao_get_notification_by_reference(reference)
    assert notification.updated_at == notification_last_updated
    assert notification.status == NOTIFICATION_DELIVERED


@pytest.mark.parametrize("next_status", [
    NOTIFICATION_CREATED,
    NOTIFICATION_SENDING,
    NOTIFICATION_PENDING,
    NOTIFICATION_SENT
])
def test_update_notification_status_by_id_cannot_exit_delivered_status_after_intermediate_state(
        sample_template,
        next_status
):
    reference = str(uuid.uuid4())

    # create notification object
    create_notification(
        sample_template,
        reference=reference,
        sent_at=datetime.now()
    )

    # get the notification object
    notification = dao_get_notification_by_reference(reference)

    # check the values that attempt_to_get_notification() return against what we sent
    assert isinstance(notification, Notification)
    assert notification.status == NOTIFICATION_CREATED

    update_notification_status_by_id(
        notification_id=notification.id,
        status=next_status
    )

    # record the last update value that is in the database
    notification_last_updated = notification.updated_at

    # get the notification object and make sure it has the values you gave it
    # establish sending as the intermediate step
    notification = dao_get_notification_by_reference(reference)
    assert isinstance(notification, Notification)
    assert notification.status == next_status

    # set notification to delivered
    update_notification_status_by_id(
        notification_id=notification.id,
        status=NOTIFICATION_DELIVERED,
        current_status=next_status
    )

    notification = dao_get_notification_by_reference(reference)
    assert notification.updated_at > notification_last_updated
    assert notification.status == NOTIFICATION_DELIVERED

    # attempt without the condition current state
    update_notification_status_by_id(
        notification_id=notification.id,
        status=next_status
    )

    notification = dao_get_notification_by_reference(reference)
    assert notification.status == NOTIFICATION_DELIVERED

    # attempt with the condition current state
    update_notification_status_by_id(
        notification_id=notification.id,
        status=next_status,
        current_status=NOTIFICATION_DELIVERED
    )

    notification = dao_get_notification_by_reference(reference)
    assert notification.status == NOTIFICATION_DELIVERED


def test_dao_update_notification_will_update_last_updated_without_conditions(sample_template):
    reference = str(uuid.uuid4())

    # create notification object
    create_notification(
        sample_template,
        reference=reference,
        sent_at=datetime.now(),
        status=NOTIFICATION_DELIVERED
    )

    # get the notification object
    notification = dao_get_notification_by_reference(reference)

    # check the values that attempt_to_get_notification() return against what we sent
    assert isinstance(notification, Notification)
    assert notification.status == NOTIFICATION_DELIVERED

    # record the last update value that is in the database
    notification_last_updated = notification.updated_at

    # attempt to do an update of the object
    dao_update_notification(notification)
    notification = dao_get_notification_by_reference(reference)
    assert notification.updated_at > notification_last_updated


@pytest.mark.parametrize("current_status, next_status", (
    (NOTIFICATION_SENT, NOTIFICATION_SENDING),
    (NOTIFICATION_DELIVERED, NOTIFICATION_SENDING),
    (NOTIFICATION_DELIVERED, NOTIFICATION_SENT),
    (NOTIFICATION_DELIVERED, NOTIFICATION_PERMANENT_FAILURE),
    (NOTIFICATION_DELIVERED, NOTIFICATION_TEMPORARY_FAILURE)
))
def test_update_notification_status_by_id_cannot_update_status_out_of_order_with_invalid_values(
        sample_template,
        current_status,
        next_status
):
    reference = str(uuid.uuid4())

    # create notification object
    create_notification(
        sample_template,
        reference=reference,
        sent_at=datetime.now(),
        status=current_status
    )

    # get the notification object
    notification = dao_get_notification_by_reference(reference)

    # record the last update value that is in the database
    notification_last_updated = notification.updated_at

    # check the values that the values return against what we sent
    assert isinstance(notification, Notification)
    assert notification.status == current_status

    # attempt update without the condition current state
    update_notification_status_by_id(
        notification_id=notification.id,
        status=next_status
    )

    # get the notification object and make sure the values are unchanged
    notification = dao_get_notification_by_reference(reference)
    assert isinstance(notification, Notification)
    assert notification.status == current_status
    assert notification.updated_at == notification_last_updated

    # attempt update with the conditional current state
    update_notification_status_by_id(
        notification_id=notification.id,
        status=next_status,
        current_status=current_status
    )

    # confirm status is unchanged
    notification = dao_get_notification_by_reference(reference)
    assert notification.updated_at == notification_last_updated
    assert notification.status == current_status


@pytest.mark.parametrize("current_status, next_status", [
    (NOTIFICATION_CREATED, NOTIFICATION_SENDING),
    (NOTIFICATION_SENDING, NOTIFICATION_SENT),
    (NOTIFICATION_SENT, NOTIFICATION_DELIVERED)
])
def test_update_notification_status_by_id_can_update_status_in_order_when_given_valid_values(
        sample_template,
        current_status,
        next_status
):
    reference_tuple = (str(uuid.uuid4()), str(uuid.uuid4()))
    notification_list = []

    for ref in reference_tuple:
        # create first notification object
        create_notification(
            sample_template,
            reference=ref,
            sent_at=datetime.now(),
            status=current_status
        )

        # add the notification object to the notification list
        notification_list.append(dao_get_notification_by_reference(ref))

        # make sure we pass all the init setup
        i = len(notification_list) - 1
        assert isinstance(notification_list[i], Notification)
        assert notification_list[i].status == current_status

    # attempt update without the condition current state
    update_notification_status_by_id(
        notification_id=notification_list[0].id,
        status=next_status
    )

    # attempt update with the conditional current state
    update_notification_status_by_id(
        notification_id=notification_list[1].id,
        status=next_status,
        current_status=current_status
    )

    # get the notification object and make sure the values have changed
    for ref in reference_tuple:
        notification = dao_get_notification_by_reference(ref)
        assert isinstance(notification, Notification)
        assert notification.status == next_status
