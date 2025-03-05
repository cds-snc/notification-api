import uuid
from datetime import date

import pytest
from freezegun import freeze_time
from sqlalchemy import delete

from app.constants import (
    EMAIL_TYPE,
    LETTER_TYPE,
    SMS_TYPE,
)
from app.models import FactNotificationStatus
from tests.app.db import create_ft_notification_status


@pytest.mark.parametrize(
    'today_only, stats',
    [(False, {'requested': 2, 'delivered': 1, 'failed': 0}), (True, {'requested': 1, 'delivered': 0, 'failed': 0})],
    ids=['seven_days', 'today'],
)
def test_get_service_notification_statistics(
    notify_db_session, admin_request, sample_service, sample_template, sample_notification, today_only, stats
):
    service = sample_service()
    template = sample_template(service=service)
    create_ft_notification_status(date(2000, 1, 1), 'sms', service, count=1)
    with freeze_time('2000-01-02T12:00:00'):
        sample_notification(template=template, status='created')
        resp = admin_request.get(
            'service.get_service_notification_statistics', service_id=template.service_id, today_only=today_only
        )

    try:
        assert set(resp['data'].keys()) == {SMS_TYPE, EMAIL_TYPE, LETTER_TYPE}
        assert resp['data'][SMS_TYPE] == stats
    finally:
        stmt = delete(FactNotificationStatus).where(FactNotificationStatus.service_id == service.id)
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


def test_get_service_notification_statistics_with_unknown_service(admin_request):
    resp = admin_request.get('service.get_service_notification_statistics', service_id=uuid.uuid4())

    assert resp['data'] == {
        SMS_TYPE: {'requested': 0, 'delivered': 0, 'failed': 0},
        EMAIL_TYPE: {'requested': 0, 'delivered': 0, 'failed': 0},
        LETTER_TYPE: {'requested': 0, 'delivered': 0, 'failed': 0},
    }
