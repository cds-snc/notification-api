import pytest
from app.dao.notifications_dao import dao_get_last_template_usage
from app.models import (
    EMAIL_TYPE,
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    LETTER_TYPE,
    SMS_TYPE,
)
from datetime import datetime, timedelta


def test_last_template_usage_should_get_right_data(sample_template, sample_notification):
    template = sample_template(name='sms Template Name')
    notification = sample_notification(template=template)
    results = dao_get_last_template_usage(template.id, SMS_TYPE, notification.service_id)
    assert results.template.name == 'sms Template Name'
    assert results.template.template_type == SMS_TYPE
    assert results.created_at == notification.created_at
    assert results.template_id == template.id
    assert results.id == notification.id


@pytest.mark.parametrize('notification_type', [EMAIL_TYPE, LETTER_TYPE, SMS_TYPE])
def test_last_template_usage_should_be_able_to_get_all_template_usage_history_order_by_notification_created_at(
    sample_template,
    sample_notification,
    notification_type,
):
    template = sample_template(template_type=notification_type)

    sample_notification(template=template, created_at=datetime.utcnow() - timedelta(seconds=1))
    sample_notification(template=template, created_at=datetime.utcnow() - timedelta(seconds=2))
    sample_notification(template=template, created_at=datetime.utcnow() - timedelta(seconds=3))
    most_recent = sample_notification(template=template)

    results = dao_get_last_template_usage(template.id, notification_type, template.service_id)
    assert results.id == most_recent.id


def test_last_template_usage_should_ignore_test_keys(sample_template, sample_api_key, sample_notification):
    one_minute_ago = datetime.utcnow() - timedelta(minutes=1)
    two_minutes_ago = datetime.utcnow() - timedelta(minutes=2)
    template = sample_template()

    team_key_notification = sample_notification(
        template=template, created_at=two_minutes_ago, api_key=sample_api_key(key_type=KEY_TYPE_TEAM)
    )
    sample_notification(template=template, created_at=one_minute_ago, api_key=sample_api_key(key_type=KEY_TYPE_TEST))

    results = dao_get_last_template_usage(template.id, SMS_TYPE, template.service_id)
    assert results.id == team_key_notification.id


def test_last_template_usage_should_be_able_to_get_no_template_usage_history_if_no_notifications_using_template(
    sample_template,
):
    template = sample_template()
    results = dao_get_last_template_usage(template.id, SMS_TYPE, template.service_id)
    assert not results
