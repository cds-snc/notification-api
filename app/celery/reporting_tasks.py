import boto3
import csv
import io
from app import notify_celery
from app.config import QueueNames
from app.cronitor import cronitor
from app.dao.fact_billing_dao import (
    fetch_nightly_billing_counts,
    fetch_billing_data_for_day,
    update_fact_billing,
)
from app.dao.fact_notification_status_dao import (
    fetch_notification_status_for_day,
    update_fact_notification_status,
    fetch_notification_statuses_per_service_and_template_for_date,
)
from celery import chain
from datetime import datetime, timedelta
from flask import current_app
from notifications_utils.timezones import convert_utc_to_local_timezone
from notifications_utils.statsd_decorators import statsd


# nightly billing stats section
@notify_celery.task(name='create-nightly-billing')
@cronitor('create-nightly-billing')
@statsd(namespace='tasks')
def create_nightly_billing(day_start=None):
    # day_start is a datetime.date() object. e.g.
    # up to 4 days of data counting back from day_start is consolidated
    if day_start is None:
        day_start = convert_utc_to_local_timezone(datetime.utcnow()).date() - timedelta(days=1)
    else:
        # When calling the task its a string in the format of "YYYY-MM-DD"
        day_start = datetime.strptime(day_start, '%Y-%m-%d').date()
    for i in range(0, 4):
        process_day = day_start - timedelta(days=i)

        tasks = [
            create_nightly_billing_for_day.si(process_day.isoformat()).set(queue=QueueNames.NOTIFY),
            generate_nightly_billing_csv_report.si(process_day.isoformat()).set(queue=QueueNames.NOTIFY),
        ]

        chain(*tasks).apply_async()


@notify_celery.task(name='create-nightly-billing-for-day')
@statsd(namespace='tasks')
def create_nightly_billing_for_day(process_day):
    process_day = datetime.strptime(process_day, '%Y-%m-%d').date()

    start = datetime.utcnow()
    transit_data = fetch_billing_data_for_day(process_day=process_day)
    end = datetime.utcnow()

    current_app.logger.info(
        'create-nightly-billing-for-day %s fetched in %s seconds', process_day, (end - start).seconds
    )

    for data in transit_data:
        update_fact_billing(data, process_day)

    current_app.logger.info(
        'create-nightly-billing-for-day task complete. %s rows updated for day: %s', len(transit_data), process_day
    )


@notify_celery.task(name='generate-nightly-billing-csv-report')
@statsd(namespace='tasks')
def generate_nightly_billing_csv_report(process_day_string: str):
    process_day = datetime.strptime(process_day_string, '%Y-%m-%d').date()
    transit_data = fetch_nightly_billing_counts(process_day)
    buff = io.StringIO()

    writer = csv.writer(buff, dialect='excel', delimiter=',')
    header = [
        'date',
        'service name',
        'service id',
        'template name',
        'template id',
        'sender',
        'sender id',
        'billing code',
        'count',
        'channel type',
        'total message parts',
        'total cost',
    ]
    writer.writerow(header)
    writer.writerows((process_day,) + tuple(map(str, row)) for row in transit_data)

    csv_key = f'{process_day_string}.billing.csv'
    client = boto3.client('s3', endpoint_url=current_app.config['AWS_S3_ENDPOINT_URL'])
    client.put_object(Body=buff.getvalue(), Bucket=current_app.config['NIGHTLY_STATS_BUCKET_NAME'], Key=csv_key)
    buff.close()

    current_app.logger.info(
        'generate-nightly-billing-csv-report complete: %s rows updated for day: %s', len(transit_data), process_day
    )


# nightly notification stats section
@notify_celery.task(name='create-nightly-notification-status')
@cronitor('create-nightly-notification-status')
@statsd(namespace='tasks')
def create_nightly_notification_status(day_start=None):
    # day_start is a datetime.date() object. e.g.
    # 4 days of data counting back from day_start is consolidated
    if day_start is None:
        day_start = convert_utc_to_local_timezone(datetime.utcnow()).date() - timedelta(days=1)
    else:
        # When calling the task its a string in the format of "YYYY-MM-DD"
        day_start = datetime.strptime(day_start, '%Y-%m-%d').date()
    for i in range(0, 4):
        process_day = day_start - timedelta(days=i)

        tasks = [
            create_nightly_notification_status_for_day.si(process_day.isoformat()).set(queue=QueueNames.NOTIFY),
            generate_daily_notification_status_csv_report.si(process_day.isoformat()).set(queue=QueueNames.NOTIFY),
        ]
        chain(*tasks).apply_async()


@notify_celery.task(name='create-nightly-notification-status-for-day')
@statsd(namespace='tasks')
def create_nightly_notification_status_for_day(process_day):
    process_day = datetime.strptime(process_day, '%Y-%m-%d').date()

    start = datetime.utcnow()
    transit_data = fetch_notification_status_for_day(process_day=process_day)
    end = datetime.utcnow()
    current_app.logger.info(
        'create-nightly-notification-status-for-day %s fetched in %s seconds', process_day, (end - start).seconds
    )

    update_fact_notification_status(transit_data, process_day)

    current_app.logger.info(
        'create-nightly-notification-status-for-day task complete: %s rows updated for day: %s',
        len(transit_data),
        process_day,
    )


@notify_celery.task(name='generate-daily-notification-status-csv-report')
@statsd(namespace='tasks')
def generate_daily_notification_status_csv_report(process_day_string):
    process_day = datetime.strptime(process_day_string, '%Y-%m-%d').date()
    transit_data = fetch_notification_statuses_per_service_and_template_for_date(process_day)
    buff = io.StringIO()

    writer = csv.writer(buff, dialect='excel', delimiter=',')
    header = [
        'date',
        'service id',
        'service name',
        'template id',
        'template name',
        'status',
        'status reason',
        'count',
        'channel_type',
    ]
    writer.writerow(header)
    writer.writerows((process_day,) + tuple(map(str, row)) for row in transit_data)

    csv_key = f'{process_day_string}.stats.csv'
    client = boto3.client('s3', endpoint_url=current_app.config['AWS_S3_ENDPOINT_URL'])
    client.put_object(Body=buff.getvalue(), Bucket=current_app.config['NIGHTLY_STATS_BUCKET_NAME'], Key=csv_key)
    buff.close()

    current_app.logger.info(
        'generate-daily-notification-status-csv-report complete: %s rows written for day: %s',
        len(transit_data),
        process_day,
    )
