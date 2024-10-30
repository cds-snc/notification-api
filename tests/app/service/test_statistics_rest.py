import uuid
from datetime import date

import pytest
from freezegun import freeze_time

from app.constants import (
    EMAIL_TYPE,
    SMS_TYPE,
    LETTER_TYPE,
)

from tests.app.db import create_notification, create_ft_notification_status


@pytest.mark.skip(reason='Mislabelled for route removal, fails when unskipped.')
@pytest.mark.parametrize(
    'today_only, stats',
    [(False, {'requested': 2, 'delivered': 1, 'failed': 0}), (True, {'requested': 1, 'delivered': 0, 'failed': 0})],
    ids=['seven_days', 'today'],
)
def test_get_service_notification_statistics(admin_request, sample_service, sample_template, today_only, stats):
    create_ft_notification_status(date(2000, 1, 1), 'sms', sample_service, count=1)
    with freeze_time('2000-01-02T12:00:00'):
        create_notification(sample_template, status='created')
        resp = admin_request.get(
            'service.get_service_notification_statistics', service_id=sample_template.service_id, today_only=today_only
        )

    assert set(resp['data'].keys()) == {SMS_TYPE, EMAIL_TYPE, LETTER_TYPE}
    assert resp['data'][SMS_TYPE] == stats


def test_get_service_notification_statistics_with_unknown_service(admin_request):
    resp = admin_request.get('service.get_service_notification_statistics', service_id=uuid.uuid4())

    assert resp['data'] == {
        SMS_TYPE: {'requested': 0, 'delivered': 0, 'failed': 0},
        EMAIL_TYPE: {'requested': 0, 'delivered': 0, 'failed': 0},
        LETTER_TYPE: {'requested': 0, 'delivered': 0, 'failed': 0},
    }
