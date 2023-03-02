from datetime import datetime, timedelta

from app.dao.notifications_dao import (
    dao_create_notification,
    overall_bounce_rate_for_day,
    service_bounce_rate_for_day,
)
from app.models import KEY_TYPE_NORMAL, Notification


def _notification_json(sample_template, job_id=None, id=None, status=None):
    data = {
        "to": "hello@world.com",
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


class TestBounceRate:
    def test_bounce_rate_all_service(self, sample_email_template, sample_job):
        assert Notification.query.count() == 0

        data_1 = _notification_json(sample_email_template, job_id=sample_job.id, status="permanent-failure")
        data_2 = _notification_json(sample_email_template, job_id=sample_job.id, status="created")

        notification_1 = Notification(**data_1)
        notification_2 = Notification(**data_2)
        dao_create_notification(notification_1)
        dao_create_notification(notification_2)

        assert Notification.query.count() == 2

        result = overall_bounce_rate_for_day(2, datetime.utcnow() + timedelta(minutes=1))
        assert result[0].service_id == sample_email_template.service_id
        assert result[0].total_emails == 2
        assert result[0].hard_bounces == 1
        assert result[0].bounce_rate == 50

    def test_bounce_rate_single_service(self, sample_email_template, sample_job):
        assert Notification.query.count() == 0

        data_1 = _notification_json(sample_email_template, job_id=sample_job.id, status="permanent-failure")
        data_2 = _notification_json(sample_email_template, job_id=sample_job.id, status="created")

        notification_1 = Notification(**data_1)
        notification_2 = Notification(**data_2)
        dao_create_notification(notification_1)
        dao_create_notification(notification_2)

        assert Notification.query.count() == 2

        result = service_bounce_rate_for_day(sample_email_template.service_id, 2, datetime.utcnow() + timedelta(minutes=1))
        assert result.total_emails == 2
        assert result.hard_bounces == 1
        assert result.bounce_rate == 50

    def test_bounce_rate_single_service_no_result(self, sample_service_full_permissions, sample_email_template, sample_job):
        assert Notification.query.count() == 0

        data_1 = _notification_json(sample_email_template, job_id=sample_job.id, status="permanent-failure")
        data_2 = _notification_json(sample_email_template, job_id=sample_job.id, status="created")

        notification_1 = Notification(**data_1)
        notification_2 = Notification(**data_2)
        dao_create_notification(notification_1)
        dao_create_notification(notification_2)

        assert Notification.query.count() == 2
        assert sample_email_template.service_id != sample_service_full_permissions.id
        result = service_bounce_rate_for_day(sample_service_full_permissions.id, 2, datetime.utcnow() + timedelta(minutes=1))
        assert result is None
