import csv
import itertools
from datetime import datetime, timedelta

import click
from click_datetime import Datetime as click_dt
from flask import current_app, json
from notifications_utils.statsd_decorators import statsd
from notifications_utils.template import SMSMessageTemplate
from sqlalchemy.orm.exc import NoResultFound

from app import db
from app.aws import s3
from app.celery.letters_pdf_tasks import create_letters_pdf
from app.celery.nightly_tasks import (
    send_total_sent_notifications_to_performance_platform,
)
from app.commands import notify_command
from app.config import QueueNames
from app.dao.fact_billing_dao import (
    delete_billing_data_for_service_for_day,
    fetch_billing_data_for_day,
    get_service_ids_that_need_billing_populated,
    update_fact_billing,
)
from app.dao.services_dao import dao_fetch_service_by_id, dao_update_service
from app.dao.templates_dao import dao_get_template_by_id
from app.dao.users_dao import get_user_by_email
from app.models import KEY_TYPE_TEST, NOTIFICATION_CREATED, SMS_TYPE, Notification
from app.performance_platform.processing_time import (
    send_processing_time_for_start_and_end,
)
from app.utils import get_local_timezone_midnight_in_utc, get_midnight_for_day_before


@notify_command()
def update_notification_international_flag():
    """
    DEPRECATED. Set notifications.international=false.
    """
    # 250,000 rows takes 30 seconds to update.
    subq = "select id from notifications where international is null limit 250000"
    update = "update notifications set international = False where id in ({})".format(subq)
    result = db.session.execute(subq).fetchall()

    while len(result) > 0:
        db.session.execute(update)
        print("commit 250000 updates at {}".format(datetime.utcnow()))
        db.session.commit()
        result = db.session.execute(subq).fetchall()

    # Now update notification_history
    subq_history = "select id from notification_history where international is null limit 250000"
    update_history = "update notification_history set international = False where id in ({})".format(subq_history)
    result_history = db.session.execute(subq_history).fetchall()
    while len(result_history) > 0:
        db.session.execute(update_history)
        print("commit 250000 updates at {}".format(datetime.utcnow()))
        db.session.commit()
        result_history = db.session.execute(subq_history).fetchall()


@notify_command()
def fix_notification_statuses_not_in_sync():
    """
    DEPRECATED.
    This will be used to correct an issue where Notification._status_enum and NotificationHistory._status_fkey
    became out of sync. See 979e90a.

    Notification._status_enum is the source of truth so NotificationHistory._status_fkey will be updated with
    these values.
    """
    MAX = 10000

    subq = "SELECT id FROM notifications WHERE cast (status as text) != notification_status LIMIT {}".format(MAX)
    update = "UPDATE notifications SET notification_status = status WHERE id in ({})".format(subq)
    result = db.session.execute(subq).fetchall()

    while len(result) > 0:
        db.session.execute(update)
        print("Committed {} updates at {}".format(len(result), datetime.utcnow()))
        db.session.commit()
        result = db.session.execute(subq).fetchall()

    subq_hist = "SELECT id FROM notification_history WHERE cast (status as text) != notification_status LIMIT {}".format(MAX)
    update = "UPDATE notification_history SET notification_status = status WHERE id in ({})".format(subq_hist)
    result = db.session.execute(subq_hist).fetchall()

    while len(result) > 0:
        db.session.execute(update)
        print("Committed {} updates at {}".format(len(result), datetime.utcnow()))
        db.session.commit()
        result = db.session.execute(subq_hist).fetchall()


@notify_command()
def backfill_notification_statuses():
    """
    DEPRECATED. Populates notification_status.

    This will be used to populate the new `Notification._status_fkey` with the old
    `Notification._status_enum`
    """
    LIMIT = 250000
    subq = "SELECT id FROM notification_history WHERE notification_status is NULL LIMIT {}".format(LIMIT)
    update = "UPDATE notification_history SET notification_status = status WHERE id in ({})".format(subq)
    result = db.session.execute(subq).fetchall()

    while len(result) > 0:
        db.session.execute(update)
        print("commit {} updates at {}".format(LIMIT, datetime.utcnow()))
        db.session.commit()
        result = db.session.execute(subq).fetchall()


@notify_command()
@click.option(
    "-s",
    "--start_date",
    required=True,
    help="start date inclusive",
    type=click_dt(format="%Y-%m-%d"),
)
@click.option(
    "-e",
    "--end_date",
    required=True,
    help="end date inclusive",
    type=click_dt(format="%Y-%m-%d"),
)
def backfill_performance_platform_totals(start_date, end_date):
    """
    Send historical total messages sent to Performance Platform.

    WARNING: This does not overwrite existing data. You need to delete
             the existing data or Performance Platform will double-count.
    """

    delta = end_date - start_date

    print("Sending total messages sent for all days between {} and {}".format(start_date, end_date))

    for i in range(delta.days + 1):
        process_date = start_date + timedelta(days=i)

        print("Sending total messages sent for {}".format(process_date.isoformat()))

        send_total_sent_notifications_to_performance_platform(process_date)


@notify_command()
@click.option(
    "-s",
    "--start_date",
    required=True,
    help="start date inclusive",
    type=click_dt(format="%Y-%m-%d"),
)
@click.option(
    "-e",
    "--end_date",
    required=True,
    help="end date inclusive",
    type=click_dt(format="%Y-%m-%d"),
)
def backfill_processing_time(start_date, end_date):
    """
    Send historical processing time to Performance Platform.
    """

    delta = end_date - start_date

    print("Sending notification processing-time data for all days between {} and {}".format(start_date, end_date))

    for i in range(delta.days + 1):
        # because the tz conversion funcs talk about midnight, and the midnight before last,
        # we want to pretend we're running this from the next morning, so add one.
        process_date = start_date + timedelta(days=i + 1)

        process_start_date = get_midnight_for_day_before(process_date)
        process_end_date = get_local_timezone_midnight_in_utc(process_date)

        print(
            "Sending notification processing-time for {} - {}".format(
                process_start_date.isoformat(), process_end_date.isoformat()
            )
        )
        send_processing_time_for_start_and_end(process_start_date, process_end_date)


@notify_command(name="replay-create-pdf-letters")
@click.option(
    "-n",
    "--notification_id",
    type=click.UUID,
    required=True,
    help="Notification id of the letter that needs the create_letters_pdf task replayed",
)
def replay_create_pdf_letters(notification_id):
    print("Create task to create_letters_pdf for notification: {}".format(notification_id))
    create_letters_pdf.apply_async([str(notification_id)], queue=QueueNames.CREATE_LETTERS_PDF)


@notify_command(name="migrate-data-to-ft-billing")
@click.option(
    "-s",
    "--start_date",
    required=True,
    help="start date inclusive",
    type=click_dt(format="%Y-%m-%d"),
)
@click.option(
    "-e",
    "--end_date",
    required=True,
    help="end date inclusive",
    type=click_dt(format="%Y-%m-%d"),
)
@statsd(namespace="tasks")
def migrate_data_to_ft_billing(start_date, end_date):
    current_app.logger.info("Billing migration from date {} to {}".format(start_date, end_date))

    process_date = start_date
    total_updated = 0

    while process_date < end_date:
        start_time = datetime.utcnow()
        # migrate data into ft_billing, upserting the data if it the record already exists
        sql = """
            insert into ft_billing (bst_date, template_id, service_id, notification_type, provider, rate_multiplier,
                international, billable_units, notifications_sent, rate, postage, created_at)
                select bst_date, template_id, service_id, notification_type, provider, rate_multiplier, international,
                    sum(billable_units) as billable_units, sum(notifications_sent) as notification_sent,
                    case when notification_type = 'sms' then sms_rate else letter_rate end as rate, postage, created_at
                from (
                    select
                        n.id,
                        (n.created_at at time zone 'UTC' at time zone 'America/Toronto')::timestamp::date as bst_date,
                        coalesce(n.template_id, '00000000-0000-0000-0000-000000000000') as template_id,
                        coalesce(n.service_id, '00000000-0000-0000-0000-000000000000') as service_id,
                        n.notification_type,
                        coalesce(n.sent_by, (
                        case
                        when notification_type = 'sms' then
                            coalesce(sent_by, 'unknown')
                        when notification_type = 'letter' then
                            coalesce(sent_by, 'dvla')
                        else
                            coalesce(sent_by, 'ses')
                        end )) as provider,
                        coalesce(n.rate_multiplier,1) as rate_multiplier,
                        s.crown,
                        coalesce((select rates.rate from rates
                        where n.notification_type = rates.notification_type and n.created_at > rates.valid_from
                        order by rates.valid_from desc limit 1), 0) as sms_rate,
                        coalesce((select l.rate from letter_rates l where n.billable_units = l.sheet_count
                        and s.crown = l.crown and n.postage = l.post_class and n.created_at >= l.start_date
                        and n.created_at < coalesce(l.end_date, now()) and n.notification_type='letter'), 0)
                        as letter_rate,
                        coalesce(n.international, false) as international,
                        n.billable_units,
                        1 as notifications_sent,
                        coalesce(n.postage, 'none') as postage,
                        now() as created_at
                    from public.notification_history n
                    left join services s on s.id = n.service_id
                    where n.key_type!='test'
                    and n.notification_status in
                    ('sending', 'sent', 'delivered', 'temporary-failure', 'permanent-failure', 'failed')
                    and n.created_at >= (date :start + time '00:00:00') at time zone 'America/Toronto'
                    at time zone 'UTC'
                    and n.created_at < (date :end + time '00:00:00') at time zone 'America/Toronto' at time zone 'UTC'
                    ) as individual_record
                group by bst_date, template_id, service_id, notification_type, provider, rate_multiplier, international,
                    sms_rate, letter_rate, postage, created_at
                order by bst_date
            on conflict on constraint ft_billing_pkey do update set
             billable_units = excluded.billable_units,
             notifications_sent = excluded.notifications_sent,
             rate = excluded.rate,
             updated_at = now()
            """

        result = db.session.execute(sql, {"start": process_date, "end": process_date + timedelta(days=1)})
        db.session.commit()
        current_app.logger.info(
            "ft_billing: --- Completed took {}ms. Migrated {} rows for {}".format(
                datetime.now() - start_time, result.rowcount, process_date
            )
        )

        process_date += timedelta(days=1)

        total_updated += result.rowcount
    current_app.logger.info("Total inserted/updated records = {}".format(total_updated))


@notify_command(name="rebuild-ft-billing-for-day")
@click.option("-s", "--service_id", required=False, type=click.UUID)
@click.option(
    "-d",
    "--day",
    help="The date to recalculate, as YYYY-MM-DD",
    required=True,
    type=click_dt(format="%Y-%m-%d"),
)
def rebuild_ft_billing_for_day(service_id, day):
    """
    Rebuild the data in ft_billing for the given service_id and date
    """

    def rebuild_ft_data(process_day, service):
        deleted_rows = delete_billing_data_for_service_for_day(process_day, service)
        current_app.logger.info("deleted {} existing billing rows for {} on {}".format(deleted_rows, service, process_day))
        transit_data = fetch_billing_data_for_day(process_day=process_day, service_id=service)
        # transit_data = every row that should exist
        for data in transit_data:
            # upsert existing rows
            update_fact_billing(data, process_day)
        current_app.logger.info("added/updated {} billing rows for {} on {}".format(len(transit_data), service, process_day))

    if service_id:
        # confirm the service exists
        dao_fetch_service_by_id(service_id)
        rebuild_ft_data(day, service_id)
    else:
        services = get_service_ids_that_need_billing_populated(
            get_local_timezone_midnight_in_utc(day),
            get_local_timezone_midnight_in_utc(day + timedelta(days=1)),
        )
        for row in services:
            rebuild_ft_data(day, row.service_id)


@notify_command(name="migrate-data-to-ft-notification-status")
@click.option(
    "-s",
    "--start_date",
    required=True,
    help="start date inclusive",
    type=click_dt(format="%Y-%m-%d"),
)
@click.option(
    "-e",
    "--end_date",
    required=True,
    help="end date inclusive",
    type=click_dt(format="%Y-%m-%d"),
)
@statsd(namespace="tasks")
def migrate_data_to_ft_notification_status(start_date, end_date):
    print("Notification statuses migration from date {} to {}".format(start_date, end_date))

    process_date = start_date
    total_updated = 0

    while process_date < end_date:
        start_time = datetime.now()
        # migrate data into ft_notification_status and update if record already exists

        db.session.execute(
            "delete from ft_notification_status where bst_date = :process_date",
            {"process_date": process_date},
        )

        sql = """
            insert into ft_notification_status (bst_date, template_id, service_id, job_id, notification_type, key_type,
                notification_status, created_at, notification_count)
                select
                    (n.created_at at time zone 'UTC' at time zone 'America/Toronto')::timestamp::date as bst_date,
                    coalesce(n.template_id, '00000000-0000-0000-0000-000000000000') as template_id,
                    n.service_id,
                    coalesce(n.job_id, '00000000-0000-0000-0000-000000000000') as job_id,
                    n.notification_type,
                    n.key_type,
                    n.notification_status,
                    now() as created_at,
                    count(*) as notification_count
                from notification_history n
                where n.created_at >= (date :start + time '00:00:00') at time zone 'America/Toronto' at time zone 'UTC'
                    and n.created_at < (date :end + time '00:00:00') at time zone 'America/Toronto' at time zone 'UTC'
                group by bst_date, template_id, service_id, job_id, notification_type, key_type, notification_status
                order by bst_date
            """
        result = db.session.execute(sql, {"start": process_date, "end": process_date + timedelta(days=1)})
        db.session.commit()
        print(
            "ft_notification_status: --- Completed took {}ms. Migrated {} rows for {}.".format(
                datetime.now() - start_time, result.rowcount, process_date
            )
        )
        process_date += timedelta(days=1)

        total_updated += result.rowcount
    print("Total inserted/updated records = {}".format(total_updated))


@notify_command(name="populate-notification-postage")
@click.option(
    "-s",
    "--start_date",
    default=datetime(2017, 2, 1),
    help="start date inclusive",
    type=click_dt(format="%Y-%m-%d"),
)
@statsd(namespace="tasks")
def populate_notification_postage(start_date):
    current_app.logger.info("populating historical notification postage")

    total_updated = 0

    while start_date < datetime.utcnow():
        # process in ten day chunks
        end_date = start_date + timedelta(days=10)

        sql = """
            UPDATE {}
            SET postage = 'second'
            WHERE notification_type = 'letter' AND
            postage IS NULL AND
            created_at BETWEEN :start AND :end
            """

        execution_start = datetime.utcnow()

        if end_date > datetime.utcnow() - timedelta(days=8):
            print("Updating notifications table as well")
            db.session.execute(sql.format("notifications"), {"start": start_date, "end": end_date})

        result = db.session.execute(sql.format("notification_history"), {"start": start_date, "end": end_date})
        db.session.commit()

        current_app.logger.info(
            "notification postage took {}ms. Migrated {} rows for {} to {}".format(
                datetime.utcnow() - execution_start,
                result.rowcount,
                start_date,
                end_date,
            )
        )

        start_date += timedelta(days=10)

        total_updated += result.rowcount

    current_app.logger.info("Total inserted/updated records = {}".format(total_updated))


@notify_command(name="update-emails-to-remove-gsi")
@click.option(
    "-s",
    "--service_id",
    required=True,
    help="service id. Update all user.email_address to remove .gsi",
)
@statsd(namespace="tasks")
def update_emails_to_remove_gsi(service_id):
    users_to_update = """SELECT u.id user_id, u.name, email_address, s.id, s.name
                           FROM users u
                           JOIN user_to_service us on (u.id = us.user_id)
                           JOIN services s on (s.id = us.service_id)
                          WHERE s.id = :service_id
                            AND u.email_address ilike ('%.gsi.gov.uk%')
    """
    results = db.session.execute(users_to_update, {"service_id": service_id})
    print("Updating {} users.".format(results.rowcount))

    for user in results:
        print("User with id {} updated".format(user.user_id))

        update_stmt = """
        UPDATE users
           SET email_address = replace(replace(email_address, '.gsi.gov.uk', '.gov.uk'), '.GSI.GOV.UK', '.GOV.UK'),
               updated_at = now()
         WHERE id = :user_id
        """
        db.session.execute(update_stmt, {"user_id": str(user.user_id)})
        db.session.commit()


@notify_command(name="replay-daily-sorted-count-files")
@click.option(
    "-f",
    "--file_extension",
    required=False,
    help="File extension to search for, defaults to rs.txt",
)
@statsd(namespace="tasks")
def replay_daily_sorted_count_files(file_extension):
    bucket_location = "{}-ftp".format(current_app.config["NOTIFY_EMAIL_DOMAIN"])
    for filename in s3.get_list_of_files_by_suffix(
        bucket_name=bucket_location,
        subfolder="root/dispatch",
        suffix=file_extension or ".rs.txt",
    ):
        print("Create task to record daily sorted counts for file: ", filename)


@notify_command(name="get-letter-details-from-zips-sent-file")
@click.argument("file_paths", required=True, nargs=-1)
@statsd(namespace="tasks")
def get_letter_details_from_zips_sent_file(file_paths):
    """Get notification details from letters listed in zips_sent file(s)

    This takes one or more file paths for the zips_sent files in S3 as its parameters, for example:
    get-letter-details-from-zips-sent-file '2019-04-01/zips_sent/filename_1' '2019-04-01/zips_sent/filename_2'
    """

    rows_from_file = []

    for path in file_paths:
        file_contents = s3.get_s3_file(
            bucket_name=current_app.config["LETTERS_PDF_BUCKET_NAME"],
            file_location=path,
        )
        rows_from_file.extend(json.loads(file_contents))

    notification_references = tuple(row[18:34] for row in rows_from_file)

    sql = """
        SELECT id, service_id, reference, job_id, created_at
        FROM notifications
        WHERE reference IN :notification_references
        ORDER BY service_id, job_id"""
    result = db.session.execute(sql, {"notification_references": notification_references}).fetchall()

    with open("zips_sent_details.csv", "w") as csvfile:
        csv_writer = csv.writer(csvfile)
        csv_writer.writerow(["notification_id", "service_id", "reference", "job_id", "created_at"])

        for row in result:
            csv_writer.writerow(row)


@notify_command(name="populate-service-volume-intentions")
@click.option(
    "-f",
    "--file_name",
    required=True,
    help="Pipe delimited file containing service_id, SMS, email, letters",
)
def populate_service_volume_intentions(file_name):
    # [0] service_id
    # [1] SMS:: volume intentions for service
    # [2] Email:: volume intentions for service
    # [3] Letters:: volume intentions for service

    with open(file_name, "r") as f:
        for line in itertools.islice(f, 1, None):
            columns = line.split(",")
            print(columns)
            service = dao_fetch_service_by_id(columns[0])
            service.volume_sms = columns[1]
            service.volume_email = columns[2]
            service.volume_letter = columns[3]
            dao_update_service(service)
    print("populate-service-volume-intentions complete")


@notify_command(name="populate-go-live")
@click.option("-f", "--file_name", required=True, help="CSV file containing live service data")
def populate_go_live(file_name):
    # 0 - count, 1- Link, 2- Service ID, 3- DEPT, 4- Service Name, 5- Main contact,
    # 6- Contact detail, 7-MOU, 8- LIVE date, 9- SMS, 10 - Email, 11 - Letters, 12 -CRM, 13 - Blue badge
    import csv

    print("Populate go live user and date")
    with open(file_name, "r") as f:
        rows = csv.reader(
            f,
            quoting=csv.QUOTE_MINIMAL,
            skipinitialspace=True,
        )
        print(next(rows))  # ignore header row
        for index, row in enumerate(rows):
            print(index, row)
            service_id = row[2]
            go_live_email = row[6]
            go_live_date = datetime.strptime(row[8], "%d/%m/%Y") + timedelta(hours=12)
            print(service_id, go_live_email, go_live_date)
            try:
                if go_live_email:
                    go_live_user = get_user_by_email(go_live_email)
                else:
                    go_live_user = None
            except NoResultFound:
                print("No user found for email address: ", go_live_email)
                continue
            try:
                service = dao_fetch_service_by_id(service_id)
            except NoResultFound:
                print("No service found for: ", service_id)
                continue
            service.go_live_user = go_live_user
            service.go_live_at = go_live_date
            dao_update_service(service)


@notify_command(name="fix-billable-units")
def fix_billable_units():
    query = Notification.query.filter(
        Notification.notification_type == SMS_TYPE,
        Notification.status != NOTIFICATION_CREATED,
        Notification.sent_at == None,  # noqa
        Notification.billable_units == 0,
        Notification.key_type != KEY_TYPE_TEST,
    )

    for notification in query.all():
        template_model = dao_get_template_by_id(notification.template_id, notification.template_version)

        template = SMSMessageTemplate(
            template_model.__dict__,
            values=notification.personalisation,
            prefix=notification.service.name,
            show_prefix=notification.service.prefix_sms,
        )
        print("Updating notification: {} with {} billable_units".format(notification.id, template.fragment_count))

        Notification.query.filter(Notification.id == notification.id).update({"billable_units": template.fragment_count})
    db.session.commit()
    print("End fix_billable_units")
