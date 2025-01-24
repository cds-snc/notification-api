from datetime import datetime, time, timedelta, timezone

from flask import current_app
from sqlalchemy import Date, case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.expression import extract, literal
from sqlalchemy.types import DateTime, Integer

from app import db
from app.dao.date_util import get_query_date_based_on_retention_period
from app.models import (
    EMAIL_TYPE,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEST,
    LETTER_TYPE,
    NOTIFICATION_CANCELLED,
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_FAILED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
    SMS_TYPE,
    ApiKey,
    FactNotificationStatus,
    Notification,
    NotificationHistory,
    Service,
    Template,
    User,
)
from app.utils import (
    get_fiscal_dates,
    get_local_timezone_midnight_in_utc,
    get_local_timezone_month_from_utc_column,
)


def fetch_notification_status_for_day(process_day, service_ids=None):
    start_date = datetime.combine(process_day, time.min)
    end_date = datetime.combine(process_day + timedelta(days=1), time.min)
    # use notification_history if process day is older than 7 days
    # this is useful if we need to rebuild the ft_billing table for a date older than 7 days ago.
    current_app.logger.info("Fetch ft_notification_status for {} to {}".format(start_date, end_date))

    all_data_for_process_day = []
    service_ids = service_ids if service_ids else [x.id for x in Service.query.all()]
    # for each service
    # for each notification type
    # query notifications for day
    # if no rows try notificationHistory
    for service_id in service_ids:
        for notification_type in [EMAIL_TYPE, SMS_TYPE, LETTER_TYPE]:
            data_for_service_and_type = query_for_fact_status_data(
                table=Notification,
                start_date=start_date,
                end_date=end_date,
                notification_type=notification_type,
                service_id=service_id,
            )

            if len(data_for_service_and_type) == 0:
                data_for_service_and_type = query_for_fact_status_data(
                    table=NotificationHistory,
                    start_date=start_date,
                    end_date=end_date,
                    notification_type=notification_type,
                    service_id=service_id,
                )
            all_data_for_process_day = all_data_for_process_day + data_for_service_and_type

    return all_data_for_process_day


def query_for_fact_status_data(table, start_date, end_date, notification_type, service_id):
    query = (
        db.session.query(
            table.template_id,
            table.service_id,
            func.coalesce(table.job_id, "00000000-0000-0000-0000-000000000000").label("job_id"),
            table.notification_type,
            table.key_type,
            table.status,
            func.count().label("notification_count"),
            func.sum(table.billable_units).label("billable_units"),
        )
        .filter(
            table.created_at >= start_date,
            table.created_at < end_date,
            table.notification_type == notification_type,
            table.service_id == service_id,
            table.key_type != KEY_TYPE_TEST,
        )
        .group_by(
            table.template_id,
            table.service_id,
            "job_id",
            table.notification_type,
            table.key_type,
            table.status,
        )
    )
    return query.all()


def update_fact_notification_status(data, process_day, service_ids=None):
    if service_ids:
        FactNotificationStatus.query.filter(
            FactNotificationStatus.bst_date == process_day, FactNotificationStatus.service_id.in_(service_ids)
        ).delete()
    else:
        FactNotificationStatus.query.filter(FactNotificationStatus.bst_date == process_day).delete()

    # Prepare bulk insert data
    bulk_insert_data = [
        {
            "bst_date": process_day,
            "template_id": row.template_id,
            "service_id": row.service_id,
            "job_id": row.job_id,
            "notification_type": row.notification_type,
            "key_type": row.key_type,
            "notification_status": row.status,
            "notification_count": row.notification_count,
            "billable_units": row.billable_units,
        }
        for row in data
    ]
    try:
        if bulk_insert_data:
            db.session.bulk_insert_mappings(FactNotificationStatus, bulk_insert_data)
        db.session.commit()

    except IntegrityError as e:
        db.session.rollback()
        current_app.logger.info(f"Integrity error in update_fact_notification_status: {e}")
        raise
    except Exception as e:
        db.session.rollback()
        current_app.logger.info(f"Unexpected error in update_fact_notification_status: {e}")
        raise


def fetch_notification_status_for_service_by_month(start_date, end_date, service_id):
    filters = [
        FactNotificationStatus.service_id == service_id,
        FactNotificationStatus.bst_date >= start_date.strftime("%Y-%m-%d"),
        # This works only for timezones to the west of GMT
        FactNotificationStatus.bst_date < end_date.strftime("%Y-%m-%d"),
        FactNotificationStatus.key_type != KEY_TYPE_TEST,
    ]

    # TODO FF_ANNUAL_LIMIT removal
    if current_app.config["FF_ANNUAL_LIMIT"]:
        filters.append(FactNotificationStatus.bst_date != datetime.utcnow().date().strftime("%Y-%m-%d"))

    return (
        db.session.query(
            func.date_trunc("month", FactNotificationStatus.bst_date).label("month"),
            FactNotificationStatus.notification_type,
            FactNotificationStatus.notification_status,
            func.sum(FactNotificationStatus.notification_count).label("count"),
        )
        .filter(*filters)
        .group_by(
            func.date_trunc("month", FactNotificationStatus.bst_date).label("month"),
            FactNotificationStatus.notification_type,
            FactNotificationStatus.notification_status,
        )
        .all()
    )


def fetch_delivered_notification_stats_by_month(filter_heartbeats=None):
    query = (
        db.session.query(
            func.date_trunc("month", FactNotificationStatus.bst_date).cast(db.Text).label("month"),
            FactNotificationStatus.notification_type,
            func.sum(FactNotificationStatus.notification_count).label("count"),
        )
        .filter(
            FactNotificationStatus.key_type != KEY_TYPE_TEST,
            FactNotificationStatus.notification_status.in_([NOTIFICATION_DELIVERED, NOTIFICATION_SENT]),
            FactNotificationStatus.bst_date >= "2019-11-01",  # GC Notify start date
        )
        .group_by(
            func.date_trunc("month", FactNotificationStatus.bst_date),
            FactNotificationStatus.notification_type,
        )
        .order_by(
            func.date_trunc("month", FactNotificationStatus.bst_date).desc(),
            FactNotificationStatus.notification_type,
        )
    )
    if filter_heartbeats:
        query = query.filter(
            FactNotificationStatus.service_id != current_app.config["NOTIFY_SERVICE_ID"],
        )
    return query.all()


def fetch_notification_stats_for_trial_services():
    ServiceHistory = Service.get_history_model()

    return (
        db.session.query(
            Service.id.label("service_id"),
            Service.name.label("service_name"),
            func.date_trunc("day", Service.created_at).cast(db.Text).label("creation_date"),
            User.name.label("user_name"),
            User.email_address.label("user_email"),
            FactNotificationStatus.notification_type.label("notification_type"),
            func.sum(FactNotificationStatus.notification_count).label("notification_sum"),
        )
        .join(
            Service,
            FactNotificationStatus.service_id == Service.id,
        )
        .join(
            ServiceHistory,
            Service.id == ServiceHistory.id,
        )
        .join(
            User,
            User.id == ServiceHistory.created_by_id,
        )
        .filter(
            ServiceHistory.version == 1,
            Service.restricted,
            FactNotificationStatus.notification_status.in_([NOTIFICATION_DELIVERED, NOTIFICATION_SENT]),
        )
        .group_by(
            Service.id,
            Service.name,
            Service.created_at,
            User.name,
            User.email_address,
            FactNotificationStatus.notification_type,
        )
        .order_by(
            Service.created_at,
        )
        .all()
    )


def fetch_notification_status_for_service_for_day(bst_day, service_id):
    # Fetch data from bst_day 00:00:00 to bst_day 23:59:59
    # bst_dat is currently in UTC and the return is in UTC
    bst_day = bst_day.replace(hour=0, minute=0, second=0)
    return (
        db.session.query(
            # return current month as a datetime so the data has the same shape as the ft_notification_status query
            literal(bst_day.replace(day=1), type_=DateTime).label("month"),
            Notification.notification_type,
            Notification.status.label("notification_status"),
            func.count().label("count"),
        )
        .filter(
            Notification.created_at >= bst_day,
            Notification.created_at < bst_day + timedelta(days=1),
            Notification.service_id == service_id,
            Notification.key_type != KEY_TYPE_TEST,
        )
        .group_by(Notification.notification_type, Notification.status)
        .all()
    )


def _stats_for_days_facts(service_id, start_time, by_template=False, notification_type=None):
    """
    We want to take the data from the fact_notification_status table for bst_data>=start_date

    Returns:
        Aggregate data in a certain format for total notifications
    """
    stats_from_facts = db.session.query(
        FactNotificationStatus.notification_type.label("notification_type"),
        FactNotificationStatus.notification_status.label("status"),
        *([FactNotificationStatus.template_id.label("template_id")] if by_template else []),
        *([FactNotificationStatus.notification_count.label("count")]),
    ).filter(
        FactNotificationStatus.service_id == service_id,
        FactNotificationStatus.bst_date >= start_time,
        FactNotificationStatus.key_type != KEY_TYPE_TEST,
    )

    if notification_type:
        stats_from_facts = stats_from_facts.filter(FactNotificationStatus.notification_type == notification_type)

    return stats_from_facts


def _timing_notification_table(service_id):
    max_date_from_facts = (
        FactNotificationStatus.query.with_entities(func.max(FactNotificationStatus.bst_date))
        .filter(FactNotificationStatus.service_id == service_id)
        .scalar()
    )
    date_to_use = max_date_from_facts + timedelta(days=1) if max_date_from_facts else datetime.now(timezone.utc)
    return datetime.combine(date_to_use, time.min)


def _stats_for_today(service_id, start_time, by_template=False, notification_type=None):
    stats_for_today = (
        db.session.query(
            Notification.notification_type.cast(db.Text),
            Notification.status,
            *([Notification.template_id] if by_template else []),
            *([func.count().label("count")]),
        )
        .filter(
            Notification.created_at >= start_time,
            Notification.service_id == service_id,
            Notification.key_type != KEY_TYPE_TEST,
        )
        .group_by(
            Notification.notification_type,
            *([Notification.template_id] if by_template else []),
            Notification.status,
        )
    )
    if notification_type:
        stats_for_today = stats_for_today.filter(Notification.notification_type == notification_type)

    return stats_for_today


def fetch_notification_status_for_service_for_today_and_7_previous_days(
    service_id, by_template=False, limit_days=7, notification_type=None
):
    """
    We want to take the data from the fact_notification_status table and the notifications table and combine them
    We will take the data from notifications ONLY for today and the fact_notification_status for the last 6 days.
    In total we will have 7 days worth of data.

    As the data in facts is populated by a job, instead of
    keeping track of the job - we will find the max date in the facts table and then use that date to get the
    data from the notifications table.

    Args:
        service_id (uuid): service_id
        by_template (bool, optional): aggregate by template Defaults to False.
        limit_days (int, optional): Number of days we want to get data for - it can depend on sensitive services.
            Defaults to 7.
        notification_type (str, optional): notification type. Defaults to None which means all notification types.

    Returns:
        Aggregate data in a certain format for total notifications
    """
    facts_notification_start_time = get_query_date_based_on_retention_period(limit_days)
    stats_from_facts = _stats_for_days_facts(service_id, facts_notification_start_time, by_template, notification_type)

    start_time_notify_table = _timing_notification_table(service_id)
    stats_for_today = _stats_for_today(service_id, start_time_notify_table, by_template, notification_type)

    all_stats_table = stats_from_facts.union_all(stats_for_today).subquery()

    query = db.session.query(
        *(
            [
                Template.name.label("template_name"),
                Template.is_precompiled_letter,
                all_stats_table.c.template_id,
            ]
            if by_template
            else []
        ),
        all_stats_table.c.notification_type,
        all_stats_table.c.status,
        func.cast(func.sum(all_stats_table.c.count), Integer).label("count"),
    )

    if by_template:
        query = query.filter(all_stats_table.c.template_id == Template.id)

    return query.group_by(
        *(
            [
                Template.name,
                Template.is_precompiled_letter,
                all_stats_table.c.template_id,
            ]
            if by_template
            else []
        ),
        all_stats_table.c.notification_type,
        all_stats_table.c.status,
    ).all()


def get_total_notifications_sent_for_api_key(api_key_id):
    """
    SELECT count(*) as total_send_attempts, notification_type
    FROM notifications
    WHERE api_key_id = 'api_key_id'
    GROUP BY notification_type;
    """

    return (
        db.session.query(
            Notification.notification_type.label("notification_type"),
            func.count(Notification.id).label("total_send_attempts"),
        )
        .filter(
            Notification.api_key_id == api_key_id,
        )
        .group_by(Notification.notification_type)
        .all()
    )


def get_last_send_for_api_key(api_key_id):
    """
    SELECT last_used_timestamp as last_notification_created
    FROM api_keys
    WHERE id = 'api_key_id';

    If last_used_timestamp is null, then check notifications table/ or notification_history.
    SELECT max(created_at) as last_notification_created
    FROM notifications
    WHERE api_key_id = 'api_key_id'
    GROUP BY api_key_id;
    """
    # Fetch last_used_timestamp from api_keys table
    api_key_table = (
        db.session.query(ApiKey.last_used_timestamp.label("last_notification_created")).filter(ApiKey.id == api_key_id).all()
    )
    return [] if api_key_table[0][0] is None else api_key_table


def get_api_key_ranked_by_notifications_created(n_days_back):
    """
    SELECT
        api_keys.name,
        api_keys.key_type,
        services.name,
        b.api_key_id,
        b.service_id,
        b.last_notification_created,
        b.email_notifications,
        b.sms_notifications,
        b.total_notifications
    FROM (
        SELECT
            a.api_key_id,
            a.service_id,
            max(a.last_notification_created) as last_notification_created,
            sum(a.email_notifications) as email_notifications,
            sum(a.sms_notifications) as sms_notifications,
            sum(a.email_notifications) + sum(a.sms_notifications) as total_notifications
        FROM (
            SELECT
                api_key_id,
                service_id,
                max(created_at) as last_notification_created,
                (CASE
                    WHEN notification_type = 'email' THEN count(*)
                    ELSE 0
                END) as email_notifications,
                (CASE
                    WHEN notification_type = 'sms' THEN count(*)
                    ELSE 0
                END) as sms_notifications
            FROM notifications
            WHERE
                created_at > 'start_date'
                and api_key_id is not null
                and key_type = 'normal'
            GROUP BY api_key_id, service_id, notification_type
        ) as a
        GROUP BY a.api_key_id, a.service_id
    ) as b
    JOIN api_keys on api_keys.id = b.api_key_id
    JOIN services on services.id = b.service_id
    ORDER BY total_notifications DESC
    LIMIT 50;
    """

    start_date = datetime.utcnow() - timedelta(days=n_days_back)

    a = (
        db.session.query(
            Notification.api_key_id,
            Notification.service_id,
            func.max(Notification.created_at).label("last_notification_created"),
            case([(Notification.notification_type == EMAIL_TYPE, func.count())], else_=0).label("email_notifications"),
            case([(Notification.notification_type == SMS_TYPE, func.count())], else_=0).label("sms_notifications"),
        )
        .filter(
            Notification.created_at >= start_date,
            Notification.api_key_id is not None,
            Notification.key_type == KEY_TYPE_NORMAL,
        )
        .group_by(
            Notification.api_key_id,
            Notification.service_id,
            Notification.notification_type,
        )
        .subquery()
    )

    b = (
        db.session.query(
            a.c.api_key_id,
            a.c.service_id,
            func.max(a.c.last_notification_created).label("last_notification_created"),
            func.sum(a.c.email_notifications).label("email_notifications"),
            func.sum(a.c.sms_notifications).label("sms_notifications"),
            (func.sum(a.c.email_notifications) + func.sum(a.c.sms_notifications)).label("total_notifications"),
        )
        .group_by(a.c.api_key_id, a.c.service_id)
        .subquery()
    )

    return (
        db.session.query(
            ApiKey.name,
            ApiKey.key_type,
            Service.name,
            b.c.api_key_id,
            b.c.service_id,
            b.c.last_notification_created,
            b.c.email_notifications,
            b.c.sms_notifications,
            b.c.total_notifications,
        )
        .join(ApiKey, ApiKey.id == b.c.api_key_id)
        .join(Service, Service.id == b.c.service_id)
        .order_by(b.c.total_notifications.desc())
        .limit(50)
        .all()
    )


def fetch_notification_status_totals_for_all_services(start_date, end_date):
    stats = (
        db.session.query(
            FactNotificationStatus.notification_type.label("notification_type"),
            FactNotificationStatus.notification_status.label("status"),
            FactNotificationStatus.key_type.label("key_type"),
            func.sum(FactNotificationStatus.notification_count).label("count"),
        )
        .filter(
            FactNotificationStatus.bst_date >= start_date,
            FactNotificationStatus.bst_date <= end_date,
        )
        .group_by(
            FactNotificationStatus.notification_type,
            FactNotificationStatus.notification_status,
            FactNotificationStatus.key_type,
        )
    )
    today = get_local_timezone_midnight_in_utc(datetime.utcnow())
    if start_date <= datetime.utcnow().date() <= end_date:
        stats_for_today = (
            db.session.query(
                Notification.notification_type.cast(db.Text).label("notification_type"),
                Notification.status,
                Notification.key_type,
                func.count().label("count"),
            )
            .filter(Notification.created_at >= today)
            .group_by(
                Notification.notification_type.cast(db.Text),
                Notification.status,
                Notification.key_type,
            )
        )
        all_stats_table = stats.union_all(stats_for_today).subquery()
        query = (
            db.session.query(
                all_stats_table.c.notification_type,
                all_stats_table.c.status,
                all_stats_table.c.key_type,
                func.cast(func.sum(all_stats_table.c.count), Integer).label("count"),
            )
            .group_by(
                all_stats_table.c.notification_type,
                all_stats_table.c.status,
                all_stats_table.c.key_type,
            )
            .order_by(all_stats_table.c.notification_type)
        )
    else:
        query = stats.order_by(FactNotificationStatus.notification_type)
    return query.all()


def fetch_notification_statuses_for_job(job_id):
    return (
        db.session.query(
            FactNotificationStatus.notification_status.label("status"),
            func.sum(FactNotificationStatus.notification_count).label("count"),
        )
        .filter(
            FactNotificationStatus.job_id == job_id,
        )
        .group_by(FactNotificationStatus.notification_status)
        .all()
    )


def fetch_stats_for_all_services_by_date_range(start_date, end_date, include_from_test_key=True):
    stats = (
        db.session.query(
            FactNotificationStatus.service_id.label("service_id"),
            Service.name.label("name"),
            Service.restricted.label("restricted"),
            Service.research_mode.label("research_mode"),
            Service.active.label("active"),
            Service.created_at.label("created_at"),
            FactNotificationStatus.notification_type.label("notification_type"),
            FactNotificationStatus.notification_status.label("status"),
            func.sum(FactNotificationStatus.notification_count).label("count"),
        )
        .filter(
            FactNotificationStatus.bst_date >= start_date,
            FactNotificationStatus.bst_date <= end_date,
            FactNotificationStatus.service_id == Service.id,
        )
        .group_by(
            FactNotificationStatus.service_id.label("service_id"),
            Service.name,
            Service.restricted,
            Service.research_mode,
            Service.active,
            Service.created_at,
            FactNotificationStatus.notification_type,
            FactNotificationStatus.notification_status,
        )
        .order_by(FactNotificationStatus.service_id, FactNotificationStatus.notification_type)
    )
    if not include_from_test_key:
        stats = stats.filter(FactNotificationStatus.key_type != KEY_TYPE_TEST)

    if start_date <= datetime.utcnow().date() <= end_date:
        today = get_local_timezone_midnight_in_utc(datetime.utcnow())
        subquery = (
            db.session.query(
                Notification.notification_type.cast(db.Text).label("notification_type"),
                Notification.status.label("status"),
                Notification.service_id.label("service_id"),
                func.count(Notification.id).label("count"),
            )
            .filter(Notification.created_at >= today)
            .group_by(
                Notification.notification_type,
                Notification.status,
                Notification.service_id,
            )
        )
        if not include_from_test_key:
            subquery = subquery.filter(Notification.key_type != KEY_TYPE_TEST)
        subquery = subquery.subquery()

        stats_for_today = db.session.query(
            Service.id.label("service_id"),
            Service.name.label("name"),
            Service.restricted.label("restricted"),
            Service.research_mode.label("research_mode"),
            Service.active.label("active"),
            Service.created_at.label("created_at"),
            subquery.c.notification_type.label("notification_type"),
            subquery.c.status.label("status"),
            subquery.c.count.label("count"),
        ).outerjoin(subquery, subquery.c.service_id == Service.id)

        all_stats_table = stats.union_all(stats_for_today).subquery()
        query = (
            db.session.query(
                all_stats_table.c.service_id,
                all_stats_table.c.name,
                all_stats_table.c.restricted,
                all_stats_table.c.research_mode,
                all_stats_table.c.active,
                all_stats_table.c.created_at,
                all_stats_table.c.notification_type,
                all_stats_table.c.status,
                func.cast(func.sum(all_stats_table.c.count), Integer).label("count"),
            )
            .group_by(
                all_stats_table.c.service_id,
                all_stats_table.c.name,
                all_stats_table.c.restricted,
                all_stats_table.c.research_mode,
                all_stats_table.c.active,
                all_stats_table.c.created_at,
                all_stats_table.c.notification_type,
                all_stats_table.c.status,
            )
            .order_by(
                all_stats_table.c.name,
                all_stats_table.c.notification_type,
                all_stats_table.c.status,
            )
        )
    else:
        query = stats
    return query.all()


def fetch_monthly_template_usage_for_service(start_date, end_date, service_id):
    # services_dao.replaces dao_fetch_monthly_historical_usage_by_template_for_service
    stats = (
        db.session.query(
            FactNotificationStatus.template_id.label("template_id"),
            Template.name.label("name"),
            Template.template_type.label("template_type"),
            Template.is_precompiled_letter.label("is_precompiled_letter"),
            extract("month", FactNotificationStatus.bst_date).label("month"),
            extract("year", FactNotificationStatus.bst_date).label("year"),
            func.sum(FactNotificationStatus.notification_count).label("count"),
        )
        .join(Template, FactNotificationStatus.template_id == Template.id)
        .filter(
            FactNotificationStatus.service_id == service_id,
            FactNotificationStatus.bst_date >= start_date.strftime("%Y-%m-%d"),
            # This works only for timezones to the west of GMT
            FactNotificationStatus.bst_date < end_date.strftime("%Y-%m-%d"),
            FactNotificationStatus.key_type != KEY_TYPE_TEST,
            FactNotificationStatus.notification_status != NOTIFICATION_CANCELLED,
        )
        .group_by(
            FactNotificationStatus.template_id,
            Template.name,
            Template.template_type,
            Template.is_precompiled_letter,
            extract("month", FactNotificationStatus.bst_date).label("month"),
            extract("year", FactNotificationStatus.bst_date).label("year"),
        )
        .order_by(
            extract("year", FactNotificationStatus.bst_date),
            extract("month", FactNotificationStatus.bst_date),
            Template.name,
        )
    )

    if start_date <= datetime.utcnow() <= end_date:
        today = get_local_timezone_midnight_in_utc(datetime.utcnow())
        month = get_local_timezone_month_from_utc_column(Notification.created_at)

        stats_for_today = (
            db.session.query(
                Notification.template_id.label("template_id"),
                Template.name.label("name"),
                Template.template_type.label("template_type"),
                Template.is_precompiled_letter.label("is_precompiled_letter"),
                extract("month", month).label("month"),
                extract("year", month).label("year"),
                func.count().label("count"),
            )
            .join(
                Template,
                Notification.template_id == Template.id,
            )
            .filter(
                Notification.created_at >= today,
                Notification.service_id == service_id,
                Notification.key_type != KEY_TYPE_TEST,
                Notification.status != NOTIFICATION_CANCELLED,
            )
            .group_by(
                Notification.template_id,
                Template.hidden,
                Template.name,
                Template.template_type,
                month,
            )
        )

        all_stats_table = stats.union_all(stats_for_today).subquery()
        query = (
            db.session.query(
                all_stats_table.c.template_id,
                all_stats_table.c.name,
                all_stats_table.c.is_precompiled_letter,
                all_stats_table.c.template_type,
                func.cast(all_stats_table.c.month, Integer).label("month"),
                func.cast(all_stats_table.c.year, Integer).label("year"),
                func.cast(func.sum(all_stats_table.c.count), Integer).label("count"),
            )
            .group_by(
                all_stats_table.c.template_id,
                all_stats_table.c.name,
                all_stats_table.c.is_precompiled_letter,
                all_stats_table.c.template_type,
                all_stats_table.c.month,
                all_stats_table.c.year,
            )
            .order_by(all_stats_table.c.year, all_stats_table.c.month, all_stats_table.c.name)
        )
    else:
        query = stats
    return query.all()


def get_total_sent_notifications_for_day_and_type(day, notification_type):
    result = (
        db.session.query(func.sum(FactNotificationStatus.notification_count).label("count"))
        .filter(
            FactNotificationStatus.notification_type == notification_type,
            FactNotificationStatus.key_type != KEY_TYPE_TEST,
            FactNotificationStatus.bst_date == day,
        )
        .scalar()
    )

    return result or 0


def fetch_monthly_notification_statuses_per_service(start_date, end_date):
    return (
        db.session.query(
            func.date_trunc("month", FactNotificationStatus.bst_date).cast(Date).label("date_created"),
            Service.id.label("service_id"),
            Service.name.label("service_name"),
            FactNotificationStatus.notification_type,
            func.sum(
                case(
                    [
                        (
                            FactNotificationStatus.notification_status == NOTIFICATION_SENDING,
                            FactNotificationStatus.notification_count,
                        )
                    ],
                    else_=0,
                )
            ).label("count_sending"),
            func.sum(
                case(
                    [
                        (
                            FactNotificationStatus.notification_status == NOTIFICATION_DELIVERED,
                            FactNotificationStatus.notification_count,
                        )
                    ],
                    else_=0,
                )
            ).label("count_delivered"),
            func.sum(
                case(
                    [
                        (
                            FactNotificationStatus.notification_status.in_([NOTIFICATION_TECHNICAL_FAILURE, NOTIFICATION_FAILED]),
                            FactNotificationStatus.notification_count,
                        )
                    ],
                    else_=0,
                )
            ).label("count_technical_failure"),
            func.sum(
                case(
                    [
                        (
                            FactNotificationStatus.notification_status == NOTIFICATION_TEMPORARY_FAILURE,
                            FactNotificationStatus.notification_count,
                        )
                    ],
                    else_=0,
                )
            ).label("count_temporary_failure"),
            func.sum(
                case(
                    [
                        (
                            FactNotificationStatus.notification_status == NOTIFICATION_PERMANENT_FAILURE,
                            FactNotificationStatus.notification_count,
                        )
                    ],
                    else_=0,
                )
            ).label("count_permanent_failure"),
            func.sum(
                case(
                    [
                        (
                            FactNotificationStatus.notification_status == NOTIFICATION_SENT,
                            FactNotificationStatus.notification_count,
                        )
                    ],
                    else_=0,
                )
            ).label("count_sent"),
        )
        .join(Service, FactNotificationStatus.service_id == Service.id)
        .filter(
            FactNotificationStatus.notification_status != NOTIFICATION_CREATED,
            Service.active.is_(True),
            FactNotificationStatus.key_type != KEY_TYPE_TEST,
            Service.research_mode.is_(False),
            Service.restricted.is_(False),
            FactNotificationStatus.bst_date >= start_date,
            FactNotificationStatus.bst_date <= end_date,
        )
        .group_by(
            Service.id,
            Service.name,
            func.date_trunc("month", FactNotificationStatus.bst_date).cast(Date),
            FactNotificationStatus.notification_type,
        )
        .order_by(
            func.date_trunc("month", FactNotificationStatus.bst_date).cast(Date),
            Service.id,
            FactNotificationStatus.notification_type,
        )
        .all()
    )


def fetch_quarter_data(start_date, end_date, service_ids):
    """
    Get data for each quarter for the given year and service_ids

    Args:
        start_date (datetime obj)
        end_date (datetime obj)
        service_ids (list): list of service_ids
    """
    query = (
        db.session.query(
            FactNotificationStatus.service_id,
            FactNotificationStatus.notification_type,
            func.sum(FactNotificationStatus.notification_count).label("notification_count"),
        )
        .filter(
            FactNotificationStatus.service_id.in_(service_ids),
            FactNotificationStatus.bst_date >= start_date,
            FactNotificationStatus.bst_date <= end_date,
        )
        .group_by(FactNotificationStatus.service_id, FactNotificationStatus.notification_type)
    )
    return query.all()


def fetch_notification_status_totals_for_service_by_fiscal_year(service_id, fiscal_year, notification_type=None):
    start_date, end_date = get_fiscal_dates(year=fiscal_year)

    filters = [
        FactNotificationStatus.service_id == (service_id),
        FactNotificationStatus.bst_date >= start_date,
        FactNotificationStatus.bst_date <= end_date,
    ]

    if notification_type:
        filters.append(FactNotificationStatus.notification_type == notification_type)

    query = (
        db.session.query(func.sum(FactNotificationStatus.notification_count).label("notification_count"))
        .filter(*filters)
        .scalar()
    )
    return query or 0
