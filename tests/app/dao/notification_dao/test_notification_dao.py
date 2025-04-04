import uuid
from datetime import datetime, timedelta
from functools import partial

import pytest
from freezegun import freeze_time
from itsdangerous import BadSignature
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm.exc import NoResultFound

from app.dao.notifications_dao import (
    bulk_insert_notifications,
    dao_create_notification,
    dao_created_scheduled_notification,
    dao_delete_notifications_by_id,
    dao_get_last_notification_added_for_job_id,
    dao_get_last_template_usage,
    dao_get_notification_by_reference,
    dao_get_notification_history_by_reference,
    dao_get_notifications_by_references,
    dao_get_notifications_by_to_field,
    dao_get_scheduled_notifications,
    dao_timeout_notifications,
    dao_update_notification,
    dao_update_notifications_by_reference,
    delete_notifications_older_than_retention_by_type,
    get_latest_sent_notification_for_job,
    get_notification_by_id,
    get_notification_count_for_job,
    get_notification_for_job,
    get_notification_with_personalisation,
    get_notifications_for_job,
    get_notifications_for_service,
    is_delivery_slow_for_provider,
    notifications_not_yet_sent,
    resign_notifications,
    send_method_stats_by_service,
    set_scheduled_notification_to_processed,
    update_notification_status_by_id,
    update_notification_status_by_reference,
)
from app.dao.organisation_dao import dao_add_service_to_organisation
from app.models import (
    JOB_STATUS_IN_PROGRESS,
    JOB_STATUS_PENDING,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PENDING,
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_STATUS_TYPES,
    NOTIFICATION_STATUS_TYPES_FAILED,
    NOTIFICATION_TEMPORARY_FAILURE,
    Job,
    Notification,
    NotificationHistory,
    ScheduledNotification,
)
from tests.app.db import (
    create_api_key,
    create_job,
    create_notification,
    create_notification_history,
    create_service,
    create_template,
    save_notification,
    save_scheduled_notification,
)
from tests.conftest import set_signer_secret_key


def test_should_have_decorated_notifications_dao_functions():
    assert dao_get_last_template_usage.__wrapped__.__name__ == "dao_get_last_template_usage"  # noqa
    assert dao_create_notification.__wrapped__.__name__ == "dao_create_notification"  # noqa
    assert update_notification_status_by_id.__wrapped__.__name__ == "update_notification_status_by_id"  # noqa
    assert dao_update_notification.__wrapped__.__name__ == "dao_update_notification"  # noqa
    assert update_notification_status_by_reference.__wrapped__.__name__ == "update_notification_status_by_reference"  # noqa
    assert get_notification_for_job.__wrapped__.__name__ == "get_notification_for_job"  # noqa
    assert get_notification_count_for_job.__wrapped__.__name__ == "get_notification_count_for_job"  # noqa
    assert get_notifications_for_job.__wrapped__.__name__ == "get_notifications_for_job"  # noqa
    assert get_notification_with_personalisation.__wrapped__.__name__ == "get_notification_with_personalisation"  # noqa
    assert get_notifications_for_service.__wrapped__.__name__ == "get_notifications_for_service"  # noqa
    assert get_notification_by_id.__wrapped__.__name__ == "get_notification_by_id"  # noqa
    assert (
        delete_notifications_older_than_retention_by_type.__wrapped__.__name__
        == "delete_notifications_older_than_retention_by_type"
    )  # noqa
    assert dao_delete_notifications_by_id.__wrapped__.__name__ == "dao_delete_notifications_by_id"  # noqa


def test_should_by_able_to_update_status_by_reference(sample_email_template, ses_provider):
    data = _notification_json(sample_email_template, status="sending")

    notification = Notification(**data)
    dao_create_notification(notification)

    assert Notification.query.get(notification.id).status == "sending"
    notification.reference = "reference"
    dao_update_notification(notification)

    updated = update_notification_status_by_reference("reference", "delivered")
    assert updated.status == "delivered"
    assert Notification.query.get(notification.id).status == "delivered"


def test_should_by_able_to_update_status_by_id(sample_template, sample_job):
    with freeze_time("2000-01-01 12:00:00"):
        data = _notification_json(sample_template, job_id=sample_job.id, status="sending")
        notification = Notification(**data)
        dao_create_notification(notification)
        assert notification.status == "sending"

    assert Notification.query.get(notification.id).status == "sending"

    with freeze_time("2000-01-02 12:00:00"):
        updated = update_notification_status_by_id(notification.id, "delivered")

    assert updated.status == "delivered"
    assert updated.updated_at == datetime(2000, 1, 2, 12, 0, 0)
    assert Notification.query.get(notification.id).status == "delivered"
    assert notification.updated_at == datetime(2000, 1, 2, 12, 0, 0)
    assert notification.status == "delivered"


def test_should_update_feedback_reason_if_present(sample_template, sample_job):
    with freeze_time("2000-01-01 12:00:00"):
        data = _notification_json(sample_template, job_id=sample_job.id, status="sending")
        notification = Notification(**data)
        dao_create_notification(notification)
        assert notification.status == "sending"

    assert Notification.query.get(notification.id).status == "sending"

    with freeze_time("2000-01-02 12:00:00"):
        updated = update_notification_status_by_id(
            notification.id, status="provider-failure", feedback_reason="NO_ORIGINATION_IDENTITIES_FOUND"
        )

    assert updated.status == "provider-failure"
    assert updated.updated_at == datetime(2000, 1, 2, 12, 0, 0)
    assert updated.feedback_reason == "NO_ORIGINATION_IDENTITIES_FOUND"
    assert Notification.query.get(notification.id).status == "provider-failure"
    assert notification.updated_at == datetime(2000, 1, 2, 12, 0, 0)
    assert notification.status == "provider-failure"
    assert notification.feedback_reason == "NO_ORIGINATION_IDENTITIES_FOUND"


def test_should_not_update_status_by_id_if_not_sending_and_does_not_update_job(
    sample_job,
):
    notification = save_notification(create_notification(template=sample_job.template, status="delivered", job=sample_job))
    assert Notification.query.get(notification.id).status == "delivered"
    assert not update_notification_status_by_id(notification.id, "failed")
    assert Notification.query.get(notification.id).status == "delivered"
    assert sample_job == Job.query.get(notification.job_id)


def test_should_not_update_status_by_reference_if_not_sending_and_does_not_update_job(
    sample_job,
):
    notification = save_notification(
        create_notification(
            template=sample_job.template,
            status="delivered",
            reference="reference",
            job=sample_job,
        )
    )
    assert Notification.query.get(notification.id).status == "delivered"
    assert not update_notification_status_by_reference("reference", "failed")
    assert Notification.query.get(notification.id).status == "delivered"
    assert sample_job == Job.query.get(notification.job_id)


def test_should_update_status_by_id_if_created(sample_template, sample_notification):
    assert Notification.query.get(sample_notification.id).status == "created"
    updated = update_notification_status_by_id(sample_notification.id, "failed")
    assert Notification.query.get(sample_notification.id).status == "failed"
    assert updated.status == "failed"


def test_should_update_status_by_id_if_pending_virus_check(sample_letter_template):
    notification = save_notification(create_notification(template=sample_letter_template, status="pending-virus-check"))
    assert Notification.query.get(notification.id).status == "pending-virus-check"
    updated = update_notification_status_by_id(notification.id, "cancelled")
    assert Notification.query.get(notification.id).status == "cancelled"
    assert updated.status == "cancelled"


def test_should_update_status_by_id_and_set_sent_by(sample_template):
    notification = save_notification(create_notification(template=sample_template, status="sending"))

    updated = update_notification_status_by_id(notification.id, "delivered", sent_by="mmg")
    assert updated.status == "delivered"
    assert updated.sent_by == "mmg"


def test_should_not_update_status_by_reference_if_from_country_with_no_delivery_receipts(
    sample_template,
):
    notification = save_notification(create_notification(sample_template, status=NOTIFICATION_SENT, reference="foo"))

    res = update_notification_status_by_reference("foo", "failed")

    assert res is None
    assert notification.status == NOTIFICATION_SENT


def test_should_not_update_status_by_id_if_sent_to_country_with_unknown_delivery_receipts(
    sample_template,
):
    notification = save_notification(
        create_notification(
            sample_template,
            status=NOTIFICATION_SENT,
            international=True,
            phone_prefix="249",  # sudan has no delivery receipts (or at least, that we know about)
        )
    )

    res = update_notification_status_by_id(notification.id, "delivered")

    assert res is None
    assert notification.status == NOTIFICATION_SENT


def test_should_not_update_status_by_id_if_sent_to_country_with_carrier_delivery_receipts(
    sample_template,
):
    notification = save_notification(
        create_notification(
            sample_template,
            status=NOTIFICATION_SENT,
            international=True,
            phone_prefix="1",  # americans only have carrier delivery receipts
        )
    )

    res = update_notification_status_by_id(notification.id, "delivered")

    assert res is None
    assert notification.status == NOTIFICATION_SENT


def test_should_not_update_status_by_id_if_sent_to_country_with_delivery_receipts(
    sample_template,
):
    notification = save_notification(
        create_notification(
            sample_template,
            status=NOTIFICATION_SENT,
            international=True,
            phone_prefix="7",  # russians have full delivery receipts
        )
    )

    res = update_notification_status_by_id(notification.id, "delivered")

    assert res == notification
    assert notification.status == NOTIFICATION_DELIVERED


def test_should_not_update_status_by_reference_if_not_sending(sample_template):
    notification = save_notification(create_notification(template=sample_template, status="created", reference="reference"))
    assert Notification.query.get(notification.id).status == "created"
    updated = update_notification_status_by_reference("reference", "failed")
    assert Notification.query.get(notification.id).status == "created"
    assert not updated


def test_should_by_able_to_update_status_by_id_from_pending_to_delivered(sample_template, sample_job):
    notification = save_notification(create_notification(template=sample_template, job=sample_job, status="sending"))

    assert update_notification_status_by_id(notification_id=notification.id, status="pending")
    assert Notification.query.get(notification.id).status == "pending"

    assert update_notification_status_by_id(notification.id, "delivered")
    assert Notification.query.get(notification.id).status == "delivered"


def test_should_by_able_to_update_status_by_id_from_pending_to_temporary_failure(sample_template, sample_job):
    notification = save_notification(create_notification(template=sample_template, job=sample_job, status="sending"))

    assert update_notification_status_by_id(notification_id=notification.id, status="pending")
    assert Notification.query.get(notification.id).status == "pending"

    assert update_notification_status_by_id(notification.id, status="permanent-failure")

    assert Notification.query.get(notification.id).status == "temporary-failure"


def test_should_by_able_to_update_status_by_id_from_sending_to_permanent_failure(sample_template, sample_job):
    data = _notification_json(sample_template, job_id=sample_job.id, status="sending")
    notification = Notification(**data)
    dao_create_notification(notification)
    assert Notification.query.get(notification.id).status == "sending"

    assert update_notification_status_by_id(notification.id, status="permanent-failure")
    assert Notification.query.get(notification.id).status == "permanent-failure"


def test_should_not_update_status_once_notification_status_is_delivered(
    sample_email_template,
):
    notification = save_notification(create_notification(template=sample_email_template, status="sending"))
    assert Notification.query.get(notification.id).status == "sending"

    notification.reference = "reference"
    dao_update_notification(notification)
    update_notification_status_by_reference("reference", "delivered")
    assert Notification.query.get(notification.id).status == "delivered"

    update_notification_status_by_reference("reference", "failed")
    assert Notification.query.get(notification.id).status == "delivered"


def test_should_return_zero_count_if_no_notification_with_id():
    assert not update_notification_status_by_id(str(uuid.uuid4()), "delivered")


def test_should_return_zero_count_if_no_notification_with_reference():
    assert not update_notification_status_by_reference("something", "delivered")


def test_create_notification_creates_notification_with_personalisation(sample_template_with_placeholders, sample_job):
    assert Notification.query.count() == 0

    data = save_notification(
        create_notification(
            template=sample_template_with_placeholders,
            job=sample_job,
            personalisation={"name": "Jo"},
            status="created",
        )
    )

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data.to == notification_from_db.to
    assert data.job_id == notification_from_db.job_id
    assert data.service == notification_from_db.service
    assert data.template == notification_from_db.template
    assert data.template_version == notification_from_db.template_version
    assert data.created_at == notification_from_db.created_at
    assert notification_from_db.status == "created"
    assert {"name": "Jo"} == notification_from_db.personalisation


def test_save_notification_creates_sms(sample_template, sample_job):
    assert Notification.query.count() == 0

    data = _notification_json(sample_template, job_id=sample_job.id)

    notification = Notification(**data)
    dao_create_notification(notification)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data["to"] == notification_from_db.to
    assert data["job_id"] == notification_from_db.job_id
    assert data["service"] == notification_from_db.service
    assert data["template_id"] == notification_from_db.template_id
    assert data["template_version"] == notification_from_db.template_version
    assert data["created_at"] == notification_from_db.created_at
    assert notification_from_db.status == "created"


def test_save_notification_and_create_email(sample_email_template, sample_job):
    assert Notification.query.count() == 0

    data = _notification_json(sample_email_template, job_id=sample_job.id)

    notification = Notification(**data)
    dao_create_notification(notification)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data["to"] == notification_from_db.to
    assert data["job_id"] == notification_from_db.job_id
    assert data["service"] == notification_from_db.service
    assert data["template_id"] == notification_from_db.template_id
    assert data["template_version"] == notification_from_db.template_version
    assert data["created_at"] == notification_from_db.created_at
    assert notification_from_db.status == "created"


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
    sample_template,
):
    sample_template.service.research_mode = True
    notification = save_notification(create_notification(template=sample_template))

    assert Notification.query.count() == 1
    assert NotificationHistory.query.count() == 0

    notification.status = "delivered"
    dao_update_notification(notification)

    assert Notification.query.one().status == "delivered"
    assert NotificationHistory.query.count() == 0


def test_not_save_notification_and_not_create_stats_on_commit_error(sample_template, sample_job):
    random_id = str(uuid.uuid4())

    assert Notification.query.count() == 0
    data = _notification_json(sample_template, job_id=random_id)

    notification = Notification(**data)
    with pytest.raises(SQLAlchemyError):
        dao_create_notification(notification)

    assert Notification.query.count() == 0
    assert Job.query.get(sample_job.id).notifications_sent == 0


def test_save_notification_and_increment_job(sample_template, sample_job):
    assert Notification.query.count() == 0
    data = _notification_json(sample_template, job_id=sample_job.id)

    notification = Notification(**data)
    dao_create_notification(notification)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data["to"] == notification_from_db.to
    assert data["job_id"] == notification_from_db.job_id
    assert data["service"] == notification_from_db.service
    assert data["template_id"] == notification_from_db.template_id
    assert data["template_version"] == notification_from_db.template_version
    assert data["created_at"] == notification_from_db.created_at
    assert notification_from_db.status == "created"

    notification_2 = Notification(**data)
    dao_create_notification(notification_2)
    assert Notification.query.count() == 2


def test_save_notification_and_increment_correct_job(notify_db, notify_db_session, sample_template):
    from tests.app.conftest import create_sample_job

    job_1 = create_sample_job(notify_db, notify_db_session, sample_template.service)
    job_2 = create_sample_job(notify_db, notify_db_session, sample_template.service)

    assert Notification.query.count() == 0
    data = _notification_json(sample_template, job_id=job_1.id)

    notification = Notification(**data)
    dao_create_notification(notification)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data["to"] == notification_from_db.to
    assert data["job_id"] == notification_from_db.job_id
    assert data["service"] == notification_from_db.service
    assert data["template_id"] == notification_from_db.template_id
    assert data["template_version"] == notification_from_db.template_version
    assert data["created_at"] == notification_from_db.created_at
    assert notification_from_db.status == "created"
    assert job_1.id != job_2.id


def test_save_notification_with_no_job(sample_template):
    assert Notification.query.count() == 0
    data = _notification_json(sample_template)

    notification = Notification(**data)
    dao_create_notification(notification)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data["to"] == notification_from_db.to
    assert data["service"] == notification_from_db.service
    assert data["template_id"] == notification_from_db.template_id
    assert data["template_version"] == notification_from_db.template_version
    assert data["created_at"] == notification_from_db.created_at
    assert notification_from_db.status == "created"


def test_get_notification_with_personalisation_by_id(sample_template):
    notification = save_scheduled_notification(
        create_notification(template=sample_template, status="created"), scheduled_for="2017-05-05 14:15"
    )
    notification_from_db = get_notification_with_personalisation(sample_template.service.id, notification.id, key_type=None)
    assert notification == notification_from_db
    assert notification_from_db.scheduled_notification.scheduled_for == datetime(2017, 5, 5, 14, 15)


def test_get_notification_with_personalisation_by_id_no_result(sample_template, fake_uuid, mocker):
    mock_logger = mocker.patch("app.authentication.auth.current_app.logger.warning")
    assert get_notification_with_personalisation(sample_template.service.id, fake_uuid, key_type=None) is None
    assert mock_logger.called


def test_get_notification_by_id_when_notification_exists(sample_notification):
    notification_from_db = get_notification_by_id(sample_notification.id)

    assert sample_notification == notification_from_db


def test_get_notification_by_id_when_notification_does_not_exist(notify_db, fake_uuid):
    notification_from_db = get_notification_by_id(fake_uuid)

    assert notification_from_db is None


def test_get_notification_by_id_when_notification_exists_for_different_service(
    sample_notification,
):
    another_service = create_service(service_name="Another service")

    with pytest.raises(NoResultFound):
        get_notification_by_id(sample_notification.id, another_service.id, _raise=True)


def test_get_notifications_by_reference(sample_template):
    client_reference = "some-client-ref"
    assert len(Notification.query.all()) == 0
    save_notification(create_notification(sample_template, client_reference=client_reference))
    save_notification(create_notification(sample_template, client_reference=client_reference))
    save_notification(create_notification(sample_template, client_reference="other-ref"))
    all_notifications = get_notifications_for_service(sample_template.service_id, client_reference=client_reference).items
    assert len(all_notifications) == 2


def test_save_notification_no_job_id(sample_template):
    assert Notification.query.count() == 0
    data = _notification_json(sample_template)

    notification = Notification(**data)
    dao_create_notification(notification)

    assert Notification.query.count() == 1
    notification_from_db = Notification.query.all()[0]
    assert notification_from_db.id
    assert data["to"] == notification_from_db.to
    assert data["service"] == notification_from_db.service
    assert data["template_id"] == notification_from_db.template_id
    assert data["template_version"] == notification_from_db.template_version
    assert notification_from_db.status == "created"
    assert data.get("job_id") is None


def test_get_notification_for_job(sample_notification):
    notification_from_db = get_notification_for_job(
        sample_notification.service.id,
        sample_notification.job_id,
        sample_notification.id,
    )
    assert sample_notification == notification_from_db


def test_get_all_notifications_for_job(sample_job):
    for i in range(0, 5):
        try:
            save_notification(create_notification(template=sample_job.template, job=sample_job))
        except IntegrityError:
            pass

    notifications_from_db = get_notifications_for_job(sample_job.service.id, sample_job.id).items
    assert len(notifications_from_db) == 5


def test_get_latest_sent_notification_for_job_partially_processed_job(sample_job):
    one_s = timedelta(seconds=1)
    now = datetime.utcnow()

    test_data = [
        (now - 5 * one_s, "sent"),
        (now - 4 * one_s, "sent"),
        (now - 3 * one_s, "sent"),
        (now - 2 * one_s, "pending"),
        (now - 1 * one_s, "pending"),
        (now, "sent"),
    ]

    for updated_at, status in test_data:
        save_notification(create_notification(template=sample_job.template, job=sample_job, status=status, updated_at=updated_at))

    latest_sent_notification = get_latest_sent_notification_for_job(sample_job.id)
    assert latest_sent_notification.updated_at == now


def test_get_latest_sent_notification_for_job_no_notifications(sample_template):
    job = create_job(template=sample_template, notification_count=0, job_status=JOB_STATUS_PENDING)

    latest_sent_notification = get_latest_sent_notification_for_job(job.id)
    assert latest_sent_notification is None


def test_get_notification_count_for_job(sample_job):
    for i in range(0, 7):
        try:
            save_notification(create_notification(template=sample_job.template, job=sample_job))
        except IntegrityError:
            pass

    notification_count_from_db = get_notification_count_for_job(sample_job.service.id, sample_job.id)
    assert notification_count_from_db == 7


def test_get_all_notifications_for_job_by_status(sample_job):
    notifications = partial(get_notifications_for_job, sample_job.service.id, sample_job.id)

    for status in NOTIFICATION_STATUS_TYPES:
        save_notification(create_notification(template=sample_job.template, job=sample_job, status=status))

    assert len(notifications().items) == len(NOTIFICATION_STATUS_TYPES)

    for status in NOTIFICATION_STATUS_TYPES:
        if status == "failed":
            assert len(notifications(filter_dict={"status": status}).items) == len(NOTIFICATION_STATUS_TYPES_FAILED)
        else:
            assert len(notifications(filter_dict={"status": status}).items) == 1

    assert len(notifications(filter_dict={"status": NOTIFICATION_STATUS_TYPES[:3]}).items) == 3


def test_update_notification_sets_status(sample_notification):
    assert sample_notification.status == "created"
    sample_notification.status = "failed"
    dao_update_notification(sample_notification)
    notification_from_db = Notification.query.get(sample_notification.id)
    assert notification_from_db.status == "failed"


@freeze_time("2016-01-10")
def test_should_limit_notifications_return_by_day_limit_plus_one(sample_template):
    assert len(Notification.query.all()) == 0

    # create one notification a day between 1st and 10th
    for i in range(1, 11):
        past_date = "2016-01-{0:02d} 12:00:00".format(i)
        with freeze_time(past_date):
            save_notification(create_notification(sample_template, created_at=datetime.utcnow(), status="failed"))

    all_notifications = Notification.query.all()
    assert len(all_notifications) == 10

    all_notifications = get_notifications_for_service(sample_template.service_id, limit_days=10).items
    assert len(all_notifications) == 10

    all_notifications = get_notifications_for_service(sample_template.service_id, limit_days=1).items
    assert len(all_notifications) == 1


def test_creating_notification_does_not_add_notification_history(sample_template):
    save_notification(create_notification(template=sample_template))
    assert Notification.query.count() == 1
    assert NotificationHistory.query.count() == 0


def test_should_delete_notification_for_id(sample_template):
    notification = save_notification(create_notification(template=sample_template))

    assert Notification.query.count() == 1
    assert NotificationHistory.query.count() == 0

    dao_delete_notifications_by_id(notification.id)

    assert Notification.query.count() == 0


def test_should_delete_notification_and_ignore_history_for_research_mode(
    sample_template,
):
    sample_template.service.research_mode = True

    notification = save_notification(create_notification(template=sample_template))

    assert Notification.query.count() == 1

    dao_delete_notifications_by_id(notification.id)

    assert Notification.query.count() == 0


def test_should_delete_only_notification_with_id(sample_template):
    notification_1 = save_notification(create_notification(template=sample_template))
    notification_2 = save_notification(create_notification(template=sample_template))
    assert Notification.query.count() == 2

    dao_delete_notifications_by_id(notification_1.id)

    assert Notification.query.count() == 1
    assert Notification.query.first().id == notification_2.id


def test_should_delete_no_notifications_if_no_matching_ids(sample_template):
    save_notification(create_notification(template=sample_template))
    assert Notification.query.count() == 1

    dao_delete_notifications_by_id(uuid.uuid4())

    assert Notification.query.count() == 1


def _notification_json(sample_template, job_id=None, id=None, status=None):
    data = {
        "to": "+44709123456",
        "service": sample_template.service,
        "service_id": sample_template.service.id,
        "template_id": sample_template.id,
        "template_version": sample_template.version,
        "created_at": datetime.utcnow(),
        "billable_units": 1,
        "notification_type": sample_template.template_type,
        "key_type": KEY_TYPE_NORMAL,
    }
    if job_id:
        data.update({"job_id": job_id})
    if id:
        data.update({"id": id})
    if status:
        data.update({"status": status})
    return data


def test_dao_timeout_notifications(sample_template):
    with freeze_time(datetime.utcnow() - timedelta(minutes=2)):
        created = save_notification(create_notification(sample_template, status="created"))
        sending = save_notification(create_notification(sample_template, status="sending"))
        pending = save_notification(create_notification(sample_template, status="pending"))
        delivered = save_notification(create_notification(sample_template, status="delivered"))

    assert Notification.query.get(created.id).status == "created"
    assert Notification.query.get(sending.id).status == "sending"
    assert Notification.query.get(pending.id).status == "pending"
    assert Notification.query.get(delivered.id).status == "delivered"
    (
        technical_failure_notifications,
        temporary_failure_notifications,
    ) = dao_timeout_notifications(1)
    assert Notification.query.get(created.id).status == "technical-failure"
    assert Notification.query.get(sending.id).status == "temporary-failure"
    assert Notification.query.get(pending.id).status == "temporary-failure"
    assert Notification.query.get(delivered.id).status == "delivered"
    assert len(technical_failure_notifications + temporary_failure_notifications) == 3


def test_dao_timeout_notifications_only_updates_for_older_notifications(
    sample_template,
):
    with freeze_time(datetime.utcnow() + timedelta(minutes=10)):
        created = save_notification(create_notification(sample_template, status="created"))
        sending = save_notification(create_notification(sample_template, status="sending"))
        pending = save_notification(create_notification(sample_template, status="pending"))
        delivered = save_notification(create_notification(sample_template, status="delivered"))

    assert Notification.query.get(created.id).status == "created"
    assert Notification.query.get(sending.id).status == "sending"
    assert Notification.query.get(pending.id).status == "pending"
    assert Notification.query.get(delivered.id).status == "delivered"
    (
        technical_failure_notifications,
        temporary_failure_notifications,
    ) = dao_timeout_notifications(1)
    assert len(technical_failure_notifications + temporary_failure_notifications) == 0


def test_dao_timeout_notifications_doesnt_affect_letters(sample_letter_template):
    with freeze_time(datetime.utcnow() - timedelta(minutes=2)):
        created = save_notification(create_notification(sample_letter_template, status="created"))
        sending = save_notification(create_notification(sample_letter_template, status="sending"))
        pending = save_notification(create_notification(sample_letter_template, status="pending"))
        delivered = save_notification(create_notification(sample_letter_template, status="delivered"))

    assert Notification.query.get(created.id).status == "created"
    assert Notification.query.get(sending.id).status == "sending"
    assert Notification.query.get(pending.id).status == "pending"
    assert Notification.query.get(delivered.id).status == "delivered"

    (
        technical_failure_notifications,
        temporary_failure_notifications,
    ) = dao_timeout_notifications(1)


def test_should_return_notifications_excluding_jobs_by_default(sample_template, sample_job, sample_api_key):
    save_notification(create_notification(sample_template, job=sample_job))
    without_job = save_notification(create_notification(sample_template, api_key=sample_api_key))

    include_jobs = get_notifications_for_service(sample_template.service_id, include_jobs=True).items
    assert len(include_jobs) == 2

    exclude_jobs_by_default = get_notifications_for_service(sample_template.service_id).items
    assert len(exclude_jobs_by_default) == 1
    assert exclude_jobs_by_default[0].id == without_job.id

    exclude_jobs_manually = get_notifications_for_service(sample_template.service_id, include_jobs=False).items
    assert len(exclude_jobs_manually) == 1
    assert exclude_jobs_manually[0].id == without_job.id


def test_should_return_notifications_including_one_offs_by_default(sample_user, sample_template):
    save_notification(create_notification(sample_template, one_off=True, created_by_id=sample_user.id))
    not_one_off = save_notification(create_notification(sample_template))

    exclude_one_offs = get_notifications_for_service(sample_template.service_id, include_one_off=False).items
    assert len(exclude_one_offs) == 1
    assert exclude_one_offs[0].id == not_one_off.id

    include_one_offs_manually = get_notifications_for_service(sample_template.service_id, include_one_off=True).items
    assert len(include_one_offs_manually) == 2

    include_one_offs_by_default = get_notifications_for_service(sample_template.service_id).items
    assert len(include_one_offs_by_default) == 2


def test_should_not_count_pages_when_given_a_flag(sample_user, sample_template):
    save_notification(create_notification(sample_template))
    notification = save_notification(create_notification(sample_template))

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
    sample_test_api_key,
):
    save_notification(create_notification(template=sample_job.template, created_at=datetime.utcnow(), job=sample_job))
    save_notification(
        create_notification(
            template=sample_job.template,
            created_at=datetime.utcnow(),
            api_key=sample_api_key,
            key_type=sample_api_key.key_type,
        )
    )
    save_notification(
        create_notification(
            template=sample_job.template,
            created_at=datetime.utcnow(),
            api_key=sample_team_api_key,
            key_type=sample_team_api_key.key_type,
        )
    )
    save_notification(
        create_notification(
            template=sample_job.template,
            created_at=datetime.utcnow(),
            api_key=sample_test_api_key,
            key_type=sample_test_api_key.key_type,
        )
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


def test_get_notifications_with_a_live_api_key_type(sample_job, sample_api_key, sample_team_api_key, sample_test_api_key):
    save_notification(create_notification(template=sample_job.template, created_at=datetime.utcnow(), job=sample_job))
    save_notification(
        create_notification(
            template=sample_job.template,
            created_at=datetime.utcnow(),
            api_key=sample_api_key,
            key_type=sample_api_key.key_type,
        )
    )
    save_notification(
        create_notification(
            template=sample_job.template,
            created_at=datetime.utcnow(),
            api_key=sample_team_api_key,
            key_type=sample_team_api_key.key_type,
        )
    )
    save_notification(
        create_notification(
            template=sample_job.template,
            created_at=datetime.utcnow(),
            api_key=sample_test_api_key,
            key_type=sample_test_api_key.key_type,
        )
    )

    all_notifications = Notification.query.all()
    assert len(all_notifications) == 4

    # only those created with normal API key, no jobs
    all_notifications = get_notifications_for_service(sample_job.service.id, limit_days=1, key_type=KEY_TYPE_NORMAL).items
    assert len(all_notifications) == 1

    # only those created with normal API key, with jobs
    all_notifications = get_notifications_for_service(
        sample_job.service.id, limit_days=1, include_jobs=True, key_type=KEY_TYPE_NORMAL
    ).items
    assert len(all_notifications) == 2


def test_get_notifications_with_a_test_api_key_type(sample_job, sample_api_key, sample_team_api_key, sample_test_api_key):
    save_notification(create_notification(template=sample_job.template, created_at=datetime.utcnow(), job=sample_job))
    save_notification(
        create_notification(
            template=sample_job.template,
            created_at=datetime.utcnow(),
            api_key=sample_api_key,
            key_type=sample_api_key.key_type,
        )
    )
    save_notification(
        create_notification(
            template=sample_job.template,
            created_at=datetime.utcnow(),
            api_key=sample_team_api_key,
            key_type=sample_team_api_key.key_type,
        )
    )
    save_notification(
        create_notification(
            template=sample_job.template,
            created_at=datetime.utcnow(),
            api_key=sample_test_api_key,
            key_type=sample_test_api_key.key_type,
        )
    )

    # only those created with test API key, no jobs
    all_notifications = get_notifications_for_service(sample_job.service_id, limit_days=1, key_type=KEY_TYPE_TEST).items
    assert len(all_notifications) == 1

    # only those created with test API key, no jobs, even when requested
    all_notifications = get_notifications_for_service(
        sample_job.service_id, limit_days=1, include_jobs=True, key_type=KEY_TYPE_TEST
    ).items
    assert len(all_notifications) == 1


def test_get_notifications_with_a_team_api_key_type(sample_job, sample_api_key, sample_team_api_key, sample_test_api_key):
    save_notification(create_notification(template=sample_job.template, created_at=datetime.utcnow(), job=sample_job))
    save_notification(
        create_notification(
            template=sample_job.template,
            created_at=datetime.utcnow(),
            api_key=sample_api_key,
            key_type=sample_api_key.key_type,
        )
    )
    save_notification(
        create_notification(
            template=sample_job.template,
            created_at=datetime.utcnow(),
            api_key=sample_team_api_key,
            key_type=sample_team_api_key.key_type,
        )
    )
    save_notification(
        create_notification(
            sample_job.template,
            created_at=datetime.utcnow(),
            api_key=sample_test_api_key,
            key_type=sample_test_api_key.key_type,
        )
    )

    # only those created with team API key, no jobs
    all_notifications = get_notifications_for_service(sample_job.service_id, limit_days=1, key_type=KEY_TYPE_TEAM).items
    assert len(all_notifications) == 1

    # only those created with team API key, no jobs, even when requested
    all_notifications = get_notifications_for_service(
        sample_job.service_id, limit_days=1, include_jobs=True, key_type=KEY_TYPE_TEAM
    ).items
    assert len(all_notifications) == 1


def test_should_exclude_test_key_notifications_by_default(sample_job, sample_api_key, sample_team_api_key, sample_test_api_key):
    save_notification(create_notification(template=sample_job.template, created_at=datetime.utcnow(), job=sample_job))

    save_notification(
        create_notification(
            template=sample_job.template,
            created_at=datetime.utcnow(),
            api_key=sample_api_key,
            key_type=sample_api_key.key_type,
        )
    )
    save_notification(
        create_notification(
            template=sample_job.template,
            created_at=datetime.utcnow(),
            api_key=sample_team_api_key,
            key_type=sample_team_api_key.key_type,
        )
    )
    save_notification(
        create_notification(
            template=sample_job.template,
            created_at=datetime.utcnow(),
            api_key=sample_test_api_key,
            key_type=sample_test_api_key.key_type,
        )
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
    ],
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
    expected_result,
):
    normal_notification = partial(
        create_notification,
        template=sample_template,
        sent_by="mmg",
        sent_at=datetime.now(),
        updated_at=datetime.now(),
    )

    slow_notification = partial(
        create_notification,
        template=sample_template,
        sent_by="mmg",
        sent_at=datetime.now() - timedelta(minutes=5),
        updated_at=datetime.now(),
    )

    for _ in range(normal_sending):
        save_notification(normal_notification(status="sending"))
    for _ in range(slow_sending):
        save_notification(slow_notification(status="sending"))
    for _ in range(normal_delivered):
        save_notification(normal_notification(status="delivered"))
    for _ in range(slow_delivered):
        save_notification(slow_notification(status="delivered"))

    assert is_delivery_slow_for_provider(datetime.utcnow(), "mmg", threshold, timedelta(minutes=4)) is expected_result


@pytest.mark.parametrize(
    "options,expected_result",
    [
        ({"status": NOTIFICATION_DELIVERED, "sent_by": "mmg"}, True),
        ({"status": NOTIFICATION_PENDING, "sent_by": "mmg"}, True),
        ({"status": NOTIFICATION_SENDING, "sent_by": "mmg"}, True),
        ({"status": NOTIFICATION_TEMPORARY_FAILURE, "sent_by": "mmg"}, False),
        ({"status": NOTIFICATION_DELIVERED, "sent_by": "mmg", "sent_at": None}, False),
        (
            {
                "status": NOTIFICATION_DELIVERED,
                "sent_by": "mmg",
                "key_type": KEY_TYPE_TEST,
            },
            False,
        ),
        ({"status": NOTIFICATION_SENDING, "sent_by": "firetext"}, False),
        ({"status": NOTIFICATION_DELIVERED, "sent_by": "firetext"}, False),
    ],
)
@freeze_time("2018-12-04 12:00:00.000000")
def test_delivery_is_delivery_slow_for_provider_filters_out_notifications_it_should_not_count(
    notify_db_session, sample_template, options, expected_result
):
    create_notification_with = {
        "template": sample_template,
        "sent_at": datetime.now() - timedelta(minutes=5),
        "updated_at": datetime.now(),
    }
    create_notification_with.update(options)
    save_notification(create_notification(**create_notification_with))
    assert is_delivery_slow_for_provider(datetime.utcnow(), "mmg", 0.1, timedelta(minutes=4)) is expected_result


def test_dao_get_notifications_by_to_field(sample_template):
    recipient_to_search_for = {
        "to_field": "+16502532222",
        "normalised_to": "+16502532222",
    }

    notification1 = save_notification(create_notification(template=sample_template, **recipient_to_search_for))
    save_notification(create_notification(template=sample_template, key_type=KEY_TYPE_TEST, **recipient_to_search_for))
    save_notification(
        create_notification(
            template=sample_template,
            to_field="jack@gmail.com",
            normalised_to="jack@gmail.com",
        )
    )
    save_notification(
        create_notification(
            template=sample_template,
            to_field="jane@gmail.com",
            normalised_to="jane@gmail.com",
        )
    )

    results = dao_get_notifications_by_to_field(
        notification1.service_id,
        recipient_to_search_for["to_field"],
        notification_type="sms",
    )

    assert len(results) == 1
    assert notification1.id == results[0].id


@pytest.mark.parametrize("search_term", ["JACK", "JACK@gmail.com", "jack@gmail.com"])
def test_dao_get_notifications_by_to_field_search_is_not_case_sensitive(sample_email_template, search_term):
    notification = save_notification(
        create_notification(
            template=sample_email_template,
            to_field="jack@gmail.com",
            normalised_to="jack@gmail.com",
        )
    )
    results = dao_get_notifications_by_to_field(notification.service_id, search_term, notification_type="email")
    notification_ids = [notification.id for notification in results]

    assert len(results) == 1
    assert notification.id in notification_ids


def test_dao_get_notifications_by_to_field_matches_partial_emails(
    sample_email_template,
):
    notification_1 = save_notification(
        create_notification(
            template=sample_email_template,
            to_field="jack@gmail.com",
            normalised_to="jack@gmail.com",
        )
    )
    notification_2 = save_notification(
        create_notification(
            template=sample_email_template,
            to_field="jacque@gmail.com",
            normalised_to="jacque@gmail.com",
        )
    )
    results = dao_get_notifications_by_to_field(notification_1.service_id, "ack", notification_type="email")
    notification_ids = [notification.id for notification in results]

    assert len(results) == 1
    assert notification_1.id in notification_ids
    assert notification_2.id not in notification_ids


@pytest.mark.parametrize(
    "search_term, expected_result_count",
    [
        ("foobar", 1),
        ("foo", 2),
        ("bar", 2),
        ("foo%", 1),
        ("%%bar", 1),
        ("%_", 1),
        ("%", 2),
        ("_", 1),
        ("/", 1),
        ("\\", 1),
        ("baz\\baz", 1),
        ("%foo", 0),
        ("%_%", 0),
        ("example.com", 5),
    ],
)
def test_dao_get_notifications_by_to_field_escapes(
    sample_email_template,
    search_term,
    expected_result_count,
):
    for email_address in {
        "foo%_@example.com",
        "%%bar@example.com",
        "foobar@example.com",
        "/@example.com",
        "baz\\baz@example.com",
    }:
        save_notification(
            create_notification(
                template=sample_email_template,
                to_field=email_address,
                normalised_to=email_address,
            )
        )

    assert (
        len(
            dao_get_notifications_by_to_field(
                sample_email_template.service_id,
                search_term,
                notification_type="email",
            )
        )
        == expected_result_count
    )


@pytest.mark.parametrize(
    "search_term",
    [
        "001",
        "100",
        "09001",
        "077009001",
        "07700 9001",
        "(0)7700 9001",
        "447700900100",
        "7700900100",
        "+4477009001",
        pytest.param(
            "+44077009001",
            marks=pytest.mark.skip(reason="No easy way to normalise this"),
        ),
        pytest.param(
            "+44(0)77009001",
            marks=pytest.mark.skip(reason="No easy way to normalise this"),
        ),
    ],
)
def test_dao_get_notifications_by_to_field_matches_partial_phone_numbers(
    sample_template,
    search_term,
):
    notification_1 = save_notification(
        create_notification(
            template=sample_template,
            to_field="+447700900100",
            normalised_to="447700900100",
        )
    )
    notification_2 = save_notification(
        create_notification(
            template=sample_template,
            to_field="+447700900200",
            normalised_to="447700900200",
        )
    )
    results = dao_get_notifications_by_to_field(notification_1.service_id, search_term, notification_type="sms")
    notification_ids = [notification.id for notification in results]

    assert len(results) == 1
    assert notification_1.id in notification_ids
    assert notification_2.id not in notification_ids


@pytest.mark.parametrize("to", ["not@email", "123"])
def test_dao_get_notifications_by_to_field_accepts_invalid_phone_numbers_and_email_addresses(
    sample_template,
    to,
):
    notification = create_notification(
        template=sample_template,
        to_field="test@example.com",
        normalised_to="test@example.com",
    )
    results = dao_get_notifications_by_to_field(notification.service_id, to, notification_type="email")
    assert len(results) == 0


def test_dao_get_notifications_by_to_field_search_ignores_spaces(sample_template):
    notification1 = save_notification(
        create_notification(template=sample_template, to_field="+16502532222", normalised_to="+16502532222")
    )
    notification2 = save_notification(
        create_notification(
            template=sample_template,
            to_field="+1 650 253 2222",
            normalised_to="+16502532222",
        )
    )
    notification3 = save_notification(
        create_notification(
            template=sample_template,
            to_field=" +1650253 2 222",
            normalised_to="+16502532222",
        )
    )
    save_notification(
        create_notification(
            template=sample_template,
            to_field="jaCK@gmail.com",
            normalised_to="jack@gmail.com",
        )
    )

    results = dao_get_notifications_by_to_field(notification1.service_id, "+16502532222", notification_type="sms")
    notification_ids = [notification.id for notification in results]

    assert len(results) == 3
    assert notification1.id in notification_ids
    assert notification2.id in notification_ids
    assert notification3.id in notification_ids


@pytest.mark.parametrize("phone_search", ("650", "502", "+16502532222"))
@pytest.mark.parametrize(
    "email_search",
    (
        "example",
        "eXaMpLe",
    ),
)
def test_dao_get_notifications_by_to_field_only_searches_one_notification_type(
    notify_db_session,
    phone_search,
    email_search,
):
    service = create_service()
    sms_template = create_template(service=service)
    email_template = create_template(service=service, template_type="email")
    sms = save_notification(create_notification(template=sms_template, to_field="6502532222", normalised_to="+16502532222"))
    email = save_notification(
        create_notification(
            template=email_template,
            to_field="165@example.com",
            normalised_to="165@example.com",
        )
    )
    results = dao_get_notifications_by_to_field(service.id, phone_search, notification_type="sms")
    assert len(results) == 1
    assert results[0].id == sms.id
    results = dao_get_notifications_by_to_field(service.id, phone_search)  # should assume SMS
    assert len(results) == 1
    assert results[0].id == sms.id
    results = dao_get_notifications_by_to_field(service.id, "165", notification_type="email")
    assert len(results) == 1
    assert results[0].id == email.id
    results = dao_get_notifications_by_to_field(service.id, email_search)  # should assume email
    assert len(results) == 1
    assert results[0].id == email.id


def test_dao_created_scheduled_notification(sample_notification):
    scheduled_notification = ScheduledNotification(
        notification_id=sample_notification.id,
        scheduled_for=datetime.strptime("2017-01-05 14:15", "%Y-%m-%d %H:%M"),
    )
    dao_created_scheduled_notification(scheduled_notification)
    saved_notification = ScheduledNotification.query.all()
    assert len(saved_notification) == 1
    assert saved_notification[0].notification_id == sample_notification.id
    assert saved_notification[0].scheduled_for == datetime(2017, 1, 5, 14, 15)


def test_dao_get_scheduled_notifications(sample_template):
    notification_1 = save_scheduled_notification(
        create_notification(template=sample_template, status="created"),
        scheduled_for="2017-05-05 14:15",
    )
    save_scheduled_notification(
        create_notification(template=sample_template, status="delivered"),
        scheduled_for="2017-05-04 14:15",
    )
    save_notification(create_notification(template=sample_template, status="created"))
    scheduled_notifications = dao_get_scheduled_notifications()
    assert len(scheduled_notifications) == 1
    assert scheduled_notifications[0].id == notification_1.id
    assert scheduled_notifications[0].scheduled_notification.pending


def test_set_scheduled_notification_to_processed(sample_template):
    notification_1 = save_scheduled_notification(
        create_notification(template=sample_template, status="created"),
        scheduled_for="2017-05-05 14:15",
    )
    scheduled_notifications = dao_get_scheduled_notifications()
    assert len(scheduled_notifications) == 1
    assert scheduled_notifications[0].id == notification_1.id
    assert scheduled_notifications[0].scheduled_notification.pending

    set_scheduled_notification_to_processed(notification_1.id)
    scheduled_notifications = dao_get_scheduled_notifications()
    assert not scheduled_notifications


def test_dao_get_notifications_by_to_field_filters_status(sample_template):
    notification = save_notification(
        create_notification(
            template=sample_template,
            to_field="+16502532222",
            normalised_to="+16502532222",
            status="delivered",
        )
    )
    save_notification(
        create_notification(
            template=sample_template,
            to_field="+16502532222",
            normalised_to="+16502532222",
            status="temporary-failure",
        )
    )

    notifications = dao_get_notifications_by_to_field(
        notification.service_id,
        "+16502532222",
        statuses=["delivered"],
        notification_type="sms",
    )

    assert len(notifications) == 1
    assert notification.id == notifications[0].id


def test_dao_get_notifications_by_to_field_filters_multiple_statuses(sample_template):
    notification1 = save_notification(
        create_notification(
            template=sample_template,
            to_field="+16502532222",
            normalised_to="+16502532222",
            status="delivered",
        )
    )
    notification2 = save_notification(
        create_notification(
            template=sample_template,
            to_field="+16502532222",
            normalised_to="+16502532222",
            status="sending",
        )
    )

    notifications = dao_get_notifications_by_to_field(
        notification1.service_id,
        "+16502532222",
        statuses=["delivered", "sending"],
        notification_type="sms",
    )
    notification_ids = [notification.id for notification in notifications]

    assert len(notifications) == 2
    assert notification1.id in notification_ids
    assert notification2.id in notification_ids


def test_dao_get_notifications_by_to_field_returns_all_if_no_status_filter(
    sample_template,
):
    notification1 = save_notification(
        create_notification(
            template=sample_template,
            to_field="+16502532222",
            normalised_to="+16502532222",
            status="delivered",
        )
    )
    notification2 = save_notification(
        create_notification(
            template=sample_template,
            to_field="+16502532222",
            normalised_to="+16502532222",
            status="temporary-failure",
        )
    )

    notifications = dao_get_notifications_by_to_field(notification1.service_id, "+16502532222", notification_type="sms")
    notification_ids = [notification.id for notification in notifications]

    assert len(notifications) == 2
    assert notification1.id in notification_ids
    assert notification2.id in notification_ids


@freeze_time("2016-01-01 11:10:00")
def test_dao_get_notifications_by_to_field_orders_by_created_at_desc(sample_template):
    data = {
        "template": sample_template,
        "to_field": "+16502532222",
        "normalised_to": "+16502532222",
    }

    notification_a_minute_ago = save_notification(
        create_notification(created_at=datetime.utcnow() - timedelta(minutes=1), **data)
    )
    notification = save_notification(create_notification(created_at=datetime.utcnow(), **data))

    notifications = dao_get_notifications_by_to_field(sample_template.service_id, "+16502532222", notification_type="sms")

    assert len(notifications) == 2
    assert notifications[0].id == notification.id
    assert notifications[1].id == notification_a_minute_ago.id


def test_dao_get_last_notification_added_for_job_id_valid_job_id(sample_template):
    job = create_job(
        template=sample_template,
        notification_count=10,
        created_at=datetime.utcnow() - timedelta(hours=2),
        scheduled_for=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_IN_PROGRESS,
    )
    create_notification(sample_template, job, 0)
    create_notification(sample_template, job, 1)
    last = create_notification(sample_template, job, 2)

    assert dao_get_last_notification_added_for_job_id(job.id) == last


def test_dao_get_last_notification_added_for_job_id_no_notifications(sample_template):
    job = create_job(
        template=sample_template,
        notification_count=10,
        created_at=datetime.utcnow() - timedelta(hours=2),
        scheduled_for=datetime.utcnow() - timedelta(minutes=31),
        processing_started=datetime.utcnow() - timedelta(minutes=31),
        job_status=JOB_STATUS_IN_PROGRESS,
    )

    assert dao_get_last_notification_added_for_job_id(job.id) is None


def test_dao_get_last_notification_added_for_job_id_no_job(sample_template, fake_uuid):
    assert dao_get_last_notification_added_for_job_id(fake_uuid) is None


def test_dao_update_notifications_by_reference_updated_notifications(sample_template):
    notification_1 = save_notification(create_notification(template=sample_template, reference="ref1"))
    notification_2 = save_notification(create_notification(template=sample_template, reference="ref2"))

    updated_count, updated_history_count = dao_update_notifications_by_reference(
        references=["ref1", "ref2"],
        update_dict={"status": "delivered", "billable_units": 2},
    )
    assert updated_count == 2
    updated_1 = Notification.query.get(notification_1.id)
    assert updated_1.billable_units == 2
    assert updated_1.status == "delivered"
    updated_2 = Notification.query.get(notification_2.id)
    assert updated_2.billable_units == 2
    assert updated_2.status == "delivered"

    assert updated_history_count == 0


def test_dao_update_notifications_by_reference_updates_history_some_notifications_exist(
    sample_template,
):
    save_notification(create_notification(template=sample_template, reference="ref1"))
    create_notification_history(template=sample_template, reference="ref2")

    updated_count, updated_history_count = dao_update_notifications_by_reference(
        references=["ref1", "ref2"],
        update_dict={"status": "delivered", "billable_units": 2},
    )
    assert updated_count == 1
    assert updated_history_count == 1


def test_dao_update_notifications_by_reference_updates_history_no_notifications_exist(
    sample_template,
):
    create_notification_history(template=sample_template, reference="ref1")
    create_notification_history(template=sample_template, reference="ref2")

    updated_count, updated_history_count = dao_update_notifications_by_reference(
        references=["ref1", "ref2"],
        update_dict={"status": "delivered", "billable_units": 2},
    )
    assert updated_count == 0
    assert updated_history_count == 2


def test_dao_update_notifications_by_reference_returns_zero_when_no_notifications_to_update(
    notify_db,
):
    updated_count, updated_history_count = dao_update_notifications_by_reference(
        references=["ref"], update_dict={"status": "delivered", "billable_units": 2}
    )

    assert updated_count == 0
    assert updated_history_count == 0


def test_dao_update_notifications_by_reference_set_returned_letter_status(
    sample_letter_template,
):
    notification = save_notification(create_notification(template=sample_letter_template, reference="ref"))

    updated_count, updated_history_count = dao_update_notifications_by_reference(
        references=["ref"], update_dict={"status": "returned-letter"}
    )

    assert updated_count == 1
    assert updated_history_count == 0
    assert Notification.query.get(notification.id).status == "returned-letter"


def test_dao_update_notifications_by_reference_updates_history_when_one_of_two_notifications_exists(
    sample_letter_template,
):
    notification1 = create_notification_history(template=sample_letter_template, reference="ref1")
    notification2 = save_notification(create_notification(template=sample_letter_template, reference="ref2"))

    updated_count, updated_history_count = dao_update_notifications_by_reference(
        references=["ref1", "ref2"], update_dict={"status": "returned-letter"}
    )

    assert updated_count == 1
    assert updated_history_count == 1
    assert Notification.query.get(notification2.id).status == "returned-letter"
    assert NotificationHistory.query.get(notification1.id).status == "returned-letter"


def test_dao_get_notification_by_reference_with_one_match_returns_notification(sample_letter_template, notify_db):
    save_notification(create_notification(template=sample_letter_template, reference="REF1"))
    notification = dao_get_notification_by_reference("REF1")

    assert notification.reference == "REF1"


def test_dao_get_notification_by_reference_with_multiple_matches_raises_error(sample_letter_template, notify_db):
    save_notification(create_notification(template=sample_letter_template, reference="REF1"))
    save_notification(create_notification(template=sample_letter_template, reference="REF1"))

    with pytest.raises(SQLAlchemyError):
        dao_get_notification_by_reference("REF1")


def test_dao_get_notification_by_reference_with_no_matches_raises_error(notify_db):
    with pytest.raises(SQLAlchemyError):
        dao_get_notification_by_reference("REF1")


def test_dao_get_notifications_by_reference(sample_template):
    save_notification(create_notification(template=sample_template, reference="noref"))
    notification_1 = save_notification(create_notification(template=sample_template, reference="ref"))
    notification_2 = save_notification(create_notification(template=sample_template, reference="ref"))

    notifications = dao_get_notifications_by_references(["ref"])
    assert len(notifications) == 2
    assert notifications[0].id in [notification_1.id, notification_2.id]
    assert notifications[1].id in [notification_1.id, notification_2.id]


def test_dao_get_notification_history_by_reference_with_one_match_returns_notification(
    sample_letter_template,
):
    save_notification(create_notification(template=sample_letter_template, reference="REF1"))
    notification = dao_get_notification_history_by_reference("REF1")

    assert notification.reference == "REF1"


def test_dao_get_notification_history_by_reference_with_multiple_matches_raises_error(
    sample_letter_template,
):
    save_notification(create_notification(template=sample_letter_template, reference="REF1"))
    save_notification(create_notification(template=sample_letter_template, reference="REF1"))

    with pytest.raises(SQLAlchemyError):
        dao_get_notification_history_by_reference("REF1")


def test_dao_get_notification_history_by_reference_with_no_matches_raises_error(
    notify_db,
):
    with pytest.raises(SQLAlchemyError):
        dao_get_notification_history_by_reference("REF1")


@pytest.mark.parametrize("notification_type", ["letter", "email", "sms"])
def test_notifications_not_yet_sent(sample_service, notification_type):
    older_than = 4  # number of seconds the notification can not be older than
    template = create_template(service=sample_service, template_type=notification_type)
    old_notification = save_notification(
        create_notification(
            template=template,
            created_at=datetime.utcnow() - timedelta(seconds=older_than),
            status="created",
        )
    )
    save_notification(
        create_notification(
            template=template,
            created_at=datetime.utcnow() - timedelta(seconds=older_than),
            status="sending",
        )
    )
    save_notification(create_notification(template=template, created_at=datetime.utcnow(), status="created"))

    results = notifications_not_yet_sent(older_than, notification_type)
    assert len(results) == 1
    assert results[0] == old_notification


@pytest.mark.parametrize("notification_type", ["letter", "email", "sms"])
def test_notifications_not_yet_sent_return_no_rows(sample_service, notification_type):
    older_than = 5  # number of seconds the notification can not be older than
    template = create_template(service=sample_service, template_type=notification_type)
    save_notification(create_notification(template=template, created_at=datetime.utcnow(), status="created"))
    save_notification(create_notification(template=template, created_at=datetime.utcnow(), status="sending"))
    save_notification(create_notification(template=template, created_at=datetime.utcnow(), status="delivered"))

    results = notifications_not_yet_sent(older_than, notification_type)
    assert len(results) == 0


@freeze_time("2020-11-01 12:00:00")
def test_send_method_stats_by_service(sample_service, sample_organisation):
    dao_add_service_to_organisation(sample_service, sample_organisation.id)
    template = create_template(service=sample_service)
    api_key = create_api_key(sample_service)

    create_notification_history(
        template=template,
        status="delivered",
        created_at=datetime.utcnow() - timedelta(days=3),
    )
    create_notification_history(
        template=template,
        status="delivered",
        api_key=api_key,
        created_at=datetime.utcnow() - timedelta(days=5),
    )
    create_notification_history(
        template=template,
        status="delivered",
        api_key=api_key,
        created_at=datetime.utcnow() - timedelta(days=6),
    )
    # Not in the results: too old
    create_notification_history(
        template=template,
        status="delivered",
        created_at=datetime.utcnow() - timedelta(days=30),
    )
    # Not in the results: status is `created`
    create_notification_history(
        template=template,
        status="created",
        created_at=datetime.utcnow() - timedelta(days=2),
    )

    assert NotificationHistory.query.count() == 5

    assert send_method_stats_by_service(
        datetime.utcnow() - timedelta(days=7),
        datetime.utcnow(),
    ) == [
        (
            sample_service.id,
            sample_service.name,
            sample_organisation.name,
            template.template_type,
            "admin",
            1,
        ),
        (
            sample_service.id,
            sample_service.name,
            sample_organisation.name,
            template.template_type,
            "api",
            2,
        ),
    ]

    assert (
        send_method_stats_by_service(
            datetime.utcnow() - timedelta(days=1),
            datetime.utcnow(),
        )
        == []
    )


class TestBulkInsertNotifications:
    def test_bulk_insert_notification(self, sample_template):
        assert len(Notification.query.all()) == 0
        n1 = create_notification(sample_template, client_reference="happy")
        n1.id = None
        n1.status = None
        n2 = create_notification(sample_template, client_reference="sad")
        n3 = create_notification(sample_template, client_reference="loud")
        bulk_insert_notifications([n1, n2, n3])
        all_notifications = get_notifications_for_service(sample_template.service_id).items
        assert len(all_notifications) == 3

    def test_bulk_insert_notification_duplicate_ids(self, sample_template):
        assert len(Notification.query.all()) == 0
        n1 = create_notification(sample_template, client_reference="happy")
        n2 = create_notification(sample_template, client_reference="sad")
        n3 = create_notification(sample_template, client_reference="loud")
        n1.id = n2.id
        n1.status = n2.status
        with pytest.raises(Exception):
            bulk_insert_notifications([n1, n2, n3])
        assert len(get_notifications_for_service(sample_template.service_id).items) == 0


class TestResigning:
    @pytest.mark.parametrize("resign,chunk_size", [(True, 2), (False, 2), (True, 10), (False, 10)])
    def test_resign_notifications_resigns_or_previews(self, resign, chunk_size, sample_template_with_placeholders):
        from app import signer_personalisation

        with set_signer_secret_key(signer_personalisation, ["k1", "k2"]):
            initial_notifications = [
                create_notification(sample_template_with_placeholders, personalisation={"Name": "test"}) for _ in range(5)
            ]
            personalisations = [n.personalisation for n in initial_notifications]
            _personalisations = [n._personalisation for n in initial_notifications]
            for notification in initial_notifications:
                save_notification(notification)

        with set_signer_secret_key(signer_personalisation, ["k2", "k3"]):
            resign_notifications(chunk_size=chunk_size, resign=resign)
            notifications = [Notification.query.get(n.id) for n in initial_notifications]
            assert [n.personalisation for n in notifications] == personalisations  # unsigned values are the same
            if resign:
                for (
                    notification,
                    _personalisation,
                ) in zip(notifications, _personalisations):
                    assert notification._personalisation != _personalisation  # signature is different
            else:
                assert [n._personalisation for n in notifications] == _personalisations  # signatures are the same

    def test_resign_notifications_fails_if_cannot_verify_signatures(self, sample_template_with_placeholders):
        from app import signer_personalisation

        with set_signer_secret_key(signer_personalisation, ["k1", "k2"]):
            initial_notification = create_notification(sample_template_with_placeholders, personalisation={"Name": "test"})
            save_notification(initial_notification)

        with set_signer_secret_key(signer_personalisation, ["k3"]):
            with pytest.raises(BadSignature):
                resign_notifications(chunk_size=10, resign=True)

    def test_resign_notifications_unsafe_resigns_with_new_key(self, sample_template_with_placeholders):
        from app import signer_personalisation

        with set_signer_secret_key(signer_personalisation, ["k1", "k2"]):
            initial_notification = create_notification(sample_template_with_placeholders, personalisation={"Name": "test"})
            save_notification(initial_notification)
            personalisation = initial_notification.personalisation
            _personalisation = initial_notification._personalisation

        with set_signer_secret_key(signer_personalisation, ["k3"]):
            resign_notifications(chunk_size=10, resign=True, unsafe=True)
            notification = Notification.query.get(initial_notification.id)
            assert notification.personalisation == personalisation  # unsigned value is the same
            assert notification._personalisation != _personalisation  # signature is different


@freeze_time("2024-09-25 12:25:00")
def test_get_notifications_for_service(sample_template):
    # create notifications for the past 10 days
    for i in range(1, 11):
        save_notification(
            create_notification(sample_template, client_reference="xyz", created_at=datetime(2024, 9, 26 - i, 23, 59, 59))
        )

    # ensure as we increase limit_days by 1, we get 1 more notification in the total each time
    for i in range(1, 11):
        assert len(get_notifications_for_service(sample_template.service_id, limit_days=i).items) == i
