from app import performance_platform_client
from app.constants import EMAIL_TYPE, LETTER_TYPE, SMS_TYPE
from app.dao.fact_notification_status_dao import get_total_sent_notifications_for_day_and_type


def send_total_notifications_sent_for_day_stats(
    start_time,
    notification_type,
    count,
):
    payload = performance_platform_client.format_payload(
        dataset='notifications', start_time=start_time, group_name='channel', group_value=notification_type, count=count
    )

    performance_platform_client.send_stats_to_performance_platform(payload)


def get_total_sent_notifications_for_day(day):
    email_count = get_total_sent_notifications_for_day_and_type(day, EMAIL_TYPE)
    sms_count = get_total_sent_notifications_for_day_and_type(day, SMS_TYPE)
    letter_count = get_total_sent_notifications_for_day_and_type(day, LETTER_TYPE)

    return {
        EMAIL_TYPE: email_count,
        SMS_TYPE: sms_count,
        LETTER_TYPE: letter_count,
    }
