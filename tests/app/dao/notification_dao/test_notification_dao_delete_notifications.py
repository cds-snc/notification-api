from datetime import date, datetime, timedelta

import pytest
from freezegun import freeze_time

from app.dao.notifications_dao import (
    delete_notifications_older_than_retention_by_type,
    insert_update_notification_history,
)
from app.models import Notification, NotificationHistory
from tests.app.db import (
    create_notification,
    create_service,
    create_service_data_retention,
    create_template,
    save_notification,
)


def create_test_data(notification_type, sample_service, days_of_retention=3):
    service_with_default_data_retention = create_service(service_name="default data retention")
    email_template, letter_template, sms_template = _create_templates(sample_service)
    (
        default_email_template,
        default_letter_template,
        default_sms_template,
    ) = _create_templates(service_with_default_data_retention)
    save_notification(create_notification(template=email_template, status="delivered"))
    save_notification(create_notification(template=sms_template, status="permanent-failure"))
    save_notification(
        create_notification(
            template=letter_template,
            status="temporary-failure",
            reference="LETTER_REF",
            sent_at=datetime.utcnow(),
        )
    )
    save_notification(
        create_notification(
            template=email_template,
            status="delivered",
            created_at=datetime.utcnow() - timedelta(days=4),
        )
    )
    save_notification(
        create_notification(
            template=sms_template,
            status="permanent-failure",
            created_at=datetime.utcnow() - timedelta(days=4),
        )
    )
    save_notification(
        create_notification(
            template=letter_template,
            status="temporary-failure",
            reference="LETTER_REF",
            sent_at=datetime.utcnow(),
            created_at=datetime.utcnow() - timedelta(days=4),
        )
    )
    save_notification(
        create_notification(
            template=default_email_template,
            status="delivered",
            created_at=datetime.utcnow() - timedelta(days=8),
        )
    )
    save_notification(
        create_notification(
            template=default_sms_template,
            status="permanent-failure",
            created_at=datetime.utcnow() - timedelta(days=8),
        )
    )
    save_notification(
        create_notification(
            template=default_letter_template,
            status="temporary-failure",
            reference="LETTER_REF",
            sent_at=datetime.utcnow(),
            created_at=datetime.utcnow() - timedelta(days=8),
        )
    )
    create_service_data_retention(
        service=sample_service,
        notification_type=notification_type,
        days_of_retention=days_of_retention,
    )


def _create_templates(sample_service):
    email_template = create_template(service=sample_service, template_type="email")
    sms_template = create_template(service=sample_service)
    letter_template = create_template(service=sample_service, template_type="letter")
    return email_template, letter_template, sms_template


@pytest.mark.parametrize("month, delete_run_time", [(4, "2016-04-10 23:40"), (1, "2016-01-11 00:40")])
@pytest.mark.parametrize(
    "notification_type, expected_sms_count, expected_email_count, expected_letter_count",
    [("sms", 7, 10, 10), ("email", 10, 7, 10)],
)
def test_should_delete_notifications_by_type_after_seven_days(
    sample_service,
    mocker,
    month,
    delete_run_time,
    notification_type,
    expected_sms_count,
    expected_email_count,
    expected_letter_count,
):
    email_template, letter_template, sms_template = _create_templates(sample_service)
    # create one notification a day between 1st and 10th from 11:00 to 19:00 of each type
    for i in range(1, 11):
        past_date = "2016-0{0}-{1:02d}  {1:02d}:00:00.000000".format(month, i)
        with freeze_time(past_date):
            save_notification(
                create_notification(
                    template=email_template,
                    created_at=datetime.utcnow(),
                    status="permanent-failure",
                )
            )
            save_notification(create_notification(template=sms_template, created_at=datetime.utcnow(), status="delivered"))
            save_notification(
                create_notification(
                    template=letter_template,
                    created_at=datetime.utcnow(),
                    status="temporary-failure",
                )
            )
    assert Notification.query.count() == 30

    # Records from before 3rd should be deleted
    with freeze_time(delete_run_time):
        delete_notifications_older_than_retention_by_type(notification_type)

    remaining_sms_notifications = Notification.query.filter_by(notification_type="sms").all()
    remaining_letter_notifications = Notification.query.filter_by(notification_type="letter").all()
    remaining_email_notifications = Notification.query.filter_by(notification_type="email").all()
    assert len(remaining_sms_notifications) == expected_sms_count
    assert len(remaining_email_notifications) == expected_email_count
    assert len(remaining_letter_notifications) == expected_letter_count

    if notification_type == "sms":
        notifications_to_check = remaining_sms_notifications
    if notification_type == "email":
        notifications_to_check = remaining_email_notifications
    if notification_type == "letter":
        notifications_to_check = remaining_letter_notifications
    for notification in notifications_to_check:
        assert notification.created_at.date() >= date(2016, month, 3)


@freeze_time("2016-01-10 12:00:00.000000")
def test_should_not_delete_notification_history(sample_service, mocker):
    with freeze_time("2016-01-01 12:00"):
        email_template, letter_template, sms_template = _create_templates(sample_service)
        save_notification(create_notification(template=email_template, status="permanent-failure"))
        save_notification(create_notification(template=sms_template, status="permanent-failure"))
        save_notification(create_notification(template=letter_template, status="permanent-failure"))
    assert Notification.query.count() == 3
    delete_notifications_older_than_retention_by_type("sms")
    assert Notification.query.count() == 2
    assert NotificationHistory.query.count() == 1


@pytest.mark.parametrize("notification_type", ["sms", "email"])
def test_delete_notifications_for_days_of_retention(sample_service, notification_type, mocker):
    create_test_data(notification_type, sample_service)
    assert Notification.query.count() == 9
    delete_notifications_older_than_retention_by_type(notification_type)
    assert Notification.query.count() == 7
    assert Notification.query.filter_by(notification_type=notification_type).count() == 1


def test_delete_notifications_inserts_notification_history(sample_service):
    create_test_data("sms", sample_service)
    assert Notification.query.count() == 9
    delete_notifications_older_than_retention_by_type("sms")
    assert Notification.query.count() == 7

    assert NotificationHistory.query.count() == 2


def test_delete_notifications_updates_notification_history(sample_email_template, mocker):
    notification = save_notification(
        create_notification(template=sample_email_template, created_at=datetime.utcnow() - timedelta(days=8))
    )
    Notification.query.filter_by(id=notification.id).update(
        {
            "status": "delivered",
            "reference": "ses_reference",
            "billable_units": 1,  # I know we don't update this for emails but this is a unit test
            "updated_at": datetime.utcnow(),
            "sent_at": datetime.utcnow(),
            "sent_by": "ses",
        }
    )

    delete_notifications_older_than_retention_by_type("email")

    history = NotificationHistory.query.all()
    assert len(history) == 1
    assert history[0].status == "delivered"
    assert history[0].reference == "ses_reference"
    assert history[0].billable_units == 1
    assert history[0].updated_at
    assert history[0].sent_by == "ses"


def test_delete_notifications_keep_data_for_days_of_retention_is_longer(sample_service):
    create_test_data("sms", sample_service, 15)
    assert Notification.query.count() == 9
    delete_notifications_older_than_retention_by_type("sms")
    assert Notification.query.count() == 8
    assert Notification.query.filter(Notification.notification_type == "sms").count() == 2


def test_delete_notifications_with_test_keys(sample_template, mocker):
    save_notification(
        create_notification(
            template=sample_template,
            key_type="test",
            created_at=datetime.utcnow() - timedelta(days=8),
        )
    )
    delete_notifications_older_than_retention_by_type("sms")
    assert Notification.query.count() == 0


def test_delete_notifications_delete_notification_type_for_default_time_if_no_days_of_retention_for_type(
    sample_service,
):
    create_service_data_retention(service=sample_service, notification_type="sms", days_of_retention=15)
    email_template, letter_template, sms_template = _create_templates(sample_service)
    save_notification(create_notification(template=email_template, status="delivered"))
    save_notification(create_notification(template=sms_template, status="permanent-failure"))
    save_notification(create_notification(template=letter_template, status="temporary-failure"))
    save_notification(
        create_notification(
            template=email_template,
            status="delivered",
            created_at=datetime.utcnow() - timedelta(days=14),
        )
    )
    save_notification(
        create_notification(
            template=sms_template,
            status="permanent-failure",
            created_at=datetime.utcnow() - timedelta(days=14),
        )
    )
    save_notification(
        create_notification(
            template=letter_template,
            status="temporary-failure",
            created_at=datetime.utcnow() - timedelta(days=14),
        )
    )
    assert Notification.query.count() == 6
    delete_notifications_older_than_retention_by_type("email")
    assert Notification.query.count() == 5
    assert Notification.query.filter_by(notification_type="email").count() == 1


@freeze_time("2016-01-10 12:00:00.000000")
def test_should_not_delete_notification_if_history_does_not_exist(sample_service, mocker):
    mocker.patch("app.dao.notifications_dao.insert_update_notification_history")
    with freeze_time("2016-01-01 12:00"):
        email_template, letter_template, sms_template = _create_templates(sample_service)
        save_notification(create_notification(template=email_template, status="permanent-failure"))
        save_notification(create_notification(template=sms_template, status="delivered"))
        save_notification(create_notification(template=letter_template, status="temporary-failure"))
    assert Notification.query.count() == 3
    delete_notifications_older_than_retention_by_type("sms")
    assert Notification.query.count() == 3
    assert NotificationHistory.query.count() == 0


def test_delete_notifications_calls_subquery_multiple_times(sample_template):
    save_notification(create_notification(template=sample_template, created_at=datetime.now() - timedelta(days=8)))
    save_notification(create_notification(template=sample_template, created_at=datetime.now() - timedelta(days=8)))
    save_notification(create_notification(template=sample_template, created_at=datetime.now() - timedelta(days=8)))

    assert Notification.query.count() == 3
    delete_notifications_older_than_retention_by_type("sms", qry_limit=1)
    assert Notification.query.count() == 0


def test_delete_notifications_returns_sum_correctly(sample_template):
    save_notification(create_notification(template=sample_template, created_at=datetime.now() - timedelta(days=8)))
    save_notification(create_notification(template=sample_template, created_at=datetime.now() - timedelta(days=8)))

    s2 = create_service(service_name="s2")
    t2 = create_template(s2, template_type="sms")
    save_notification(create_notification(template=t2, created_at=datetime.now() - timedelta(days=8)))
    save_notification(create_notification(template=t2, created_at=datetime.now() - timedelta(days=8)))

    ret = delete_notifications_older_than_retention_by_type("sms", qry_limit=1)
    assert ret == 4


def test_insert_update_notification_history(sample_service):
    template = create_template(sample_service, template_type="sms")
    notification_1 = save_notification(create_notification(template=template, created_at=datetime.utcnow() - timedelta(days=3)))
    notification_2 = save_notification(create_notification(template=template, created_at=datetime.utcnow() - timedelta(days=8)))
    notification_3 = save_notification(create_notification(template=template, created_at=datetime.utcnow() - timedelta(days=9)))
    other_types = ["email", "letter"]
    for template_type in other_types:
        t = create_template(service=sample_service, template_type=template_type)
        save_notification(create_notification(template=t, created_at=datetime.utcnow() - timedelta(days=3)))
        save_notification(create_notification(template=t, created_at=datetime.utcnow() - timedelta(days=8)))

    insert_update_notification_history(
        notification_type="sms",
        date_to_delete_from=datetime.utcnow() - timedelta(days=7),
        service_id=sample_service.id,
    )
    history = NotificationHistory.query.all()
    assert len(history) == 2

    history_ids = [x.id for x in history]
    assert notification_1.id not in history_ids
    assert notification_2.id in history_ids
    assert notification_3.id in history_ids


def test_insert_update_notification_history_only_insert_update_given_service(
    sample_service,
):
    other_service = create_service(service_name="another service")
    other_template = create_template(service=other_service)
    template = create_template(service=sample_service)
    notification_1 = save_notification(create_notification(template=template, created_at=datetime.utcnow() - timedelta(days=3)))
    notification_2 = save_notification(create_notification(template=template, created_at=datetime.utcnow() - timedelta(days=8)))
    notification_3 = save_notification(
        create_notification(template=other_template, created_at=datetime.utcnow() - timedelta(days=3))
    )
    notification_4 = save_notification(
        create_notification(template=other_template, created_at=datetime.utcnow() - timedelta(days=8))
    )

    insert_update_notification_history("sms", datetime.utcnow() - timedelta(days=7), sample_service.id)
    history = NotificationHistory.query.all()
    assert len(history) == 1

    history_ids = [x.id for x in history]
    assert notification_1.id not in history_ids
    assert notification_2.id in history_ids
    assert notification_3.id not in history_ids
    assert notification_4.id not in history_ids


def test_insert_update_notification_history_updates_history_with_new_status(
    sample_template,
):
    notification_1 = save_notification(
        create_notification(template=sample_template, created_at=datetime.utcnow() - timedelta(days=3))
    )
    notification_2 = save_notification(
        create_notification(
            template=sample_template,
            created_at=datetime.utcnow() - timedelta(days=8),
            status="delivered",
        )
    )
    insert_update_notification_history("sms", datetime.utcnow() - timedelta(days=7), sample_template.service_id)
    history = NotificationHistory.query.get(notification_2.id)
    assert history.status == "delivered"
    assert not NotificationHistory.query.get(notification_1.id)
