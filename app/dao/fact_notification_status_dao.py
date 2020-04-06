from datetime import datetime, timedelta, time

from flask import current_app
from notifications_utils.timezones import convert_local_timezone_to_utc
from sqlalchemy import case, func, Date
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql.expression import literal, extract
from sqlalchemy.types import DateTime, Integer

from app import db
from app.models import (
    ApiKey,
    EMAIL_TYPE,
    FactNotificationStatus,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEST,
    LETTER_TYPE,
    Notification,
    NotificationHistory,
    NOTIFICATION_CANCELLED,
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_FAILED,
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
    Service,
    SMS_TYPE,
    Template,
)
from app.utils import (
    get_local_timezone_midnight_in_utc,
    midnight_n_days_ago,
    get_local_timezone_month_from_utc_column, get_local_timezone_midnight
)


def fetch_notification_status_for_day(process_day, service_id=None):
    start_date = convert_local_timezone_to_utc(datetime.combine(process_day, time.min))
    end_date = convert_local_timezone_to_utc(datetime.combine(process_day + timedelta(days=1), time.min))
    # use notification_history if process day is older than 7 days
    # this is useful if we need to rebuild the ft_billing table for a date older than 7 days ago.
    current_app.logger.info("Fetch ft_notification_status for {} to {}".format(start_date, end_date))

    all_data_for_process_day = []
    service_ids = [x.id for x in Service.query.all()]
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
                service_id=service_id
            )

            if len(data_for_service_and_type) == 0:
                data_for_service_and_type = query_for_fact_status_data(
                    table=NotificationHistory,
                    start_date=start_date,
                    end_date=end_date,
                    notification_type=notification_type,
                    service_id=service_id
                )
            all_data_for_process_day = all_data_for_process_day + data_for_service_and_type

    return all_data_for_process_day


def query_for_fact_status_data(table, start_date, end_date, notification_type, service_id):
    query = db.session.query(
        table.template_id,
        table.service_id,
        func.coalesce(table.job_id, '00000000-0000-0000-0000-000000000000').label('job_id'),
        table.notification_type,
        table.key_type,
        table.status,
        func.count().label('notification_count')
    ).filter(
        table.created_at >= start_date,
        table.created_at < end_date,
        table.notification_type == notification_type,
        table.service_id == service_id,
        table.key_type != KEY_TYPE_TEST
    ).group_by(
        table.template_id,
        table.service_id,
        'job_id',
        table.notification_type,
        table.key_type,
        table.status
    )
    return query.all()


def update_fact_notification_status(data, process_day):
    table = FactNotificationStatus.__table__
    FactNotificationStatus.query.filter(
        FactNotificationStatus.bst_date == process_day
    ).delete()

    for row in data:
        stmt = insert(table).values(
            bst_date=process_day,
            template_id=row.template_id,
            service_id=row.service_id,
            job_id=row.job_id,
            notification_type=row.notification_type,
            key_type=row.key_type,
            notification_status=row.status,
            notification_count=row.notification_count,
        )
        db.session.connection().execute(stmt)
        db.session.commit()


def fetch_notification_status_for_service_by_month(start_date, end_date, service_id):
    return db.session.query(
        func.date_trunc('month', FactNotificationStatus.bst_date).label('month'),
        FactNotificationStatus.notification_type,
        FactNotificationStatus.notification_status,
        func.sum(FactNotificationStatus.notification_count).label('count')
    ).filter(
        FactNotificationStatus.service_id == service_id,
        FactNotificationStatus.bst_date >= start_date.strftime("%Y-%m-%d"),
        # This works only for timezones to the west of GMT
        FactNotificationStatus.bst_date < end_date.strftime("%Y-%m-%d"),
        FactNotificationStatus.key_type != KEY_TYPE_TEST
    ).group_by(
        func.date_trunc('month', FactNotificationStatus.bst_date).label('month'),
        FactNotificationStatus.notification_type,
        FactNotificationStatus.notification_status
    ).all()


def fetch_notification_status_for_service_for_day(bst_day, service_id):
    return db.session.query(
        # return current month as a datetime so the data has the same shape as the ft_notification_status query
        literal(bst_day.replace(day=1), type_=DateTime).label('month'),
        Notification.notification_type,
        Notification.status.label('notification_status'),
        func.count().label('count')
    ).filter(
        Notification.created_at >= get_local_timezone_midnight_in_utc(bst_day),
        Notification.created_at < get_local_timezone_midnight_in_utc(bst_day + timedelta(days=1)),
        Notification.service_id == service_id,
        Notification.key_type != KEY_TYPE_TEST
    ).group_by(
        Notification.notification_type,
        Notification.status
    ).all()


def fetch_notification_status_for_service_for_today_and_7_previous_days(service_id, by_template=False, limit_days=7):
    start_date = midnight_n_days_ago(limit_days)
    now = datetime.now()
    stats_for_7_days = db.session.query(
        FactNotificationStatus.notification_type.label('notification_type'),
        FactNotificationStatus.notification_status.label('status'),
        *([FactNotificationStatus.template_id.label('template_id')] if by_template else []),
        FactNotificationStatus.notification_count.label('count')
    ).filter(
        FactNotificationStatus.service_id == service_id,
        FactNotificationStatus.bst_date >= start_date,
        FactNotificationStatus.key_type != KEY_TYPE_TEST
    )

    stats_for_today = db.session.query(
        Notification.notification_type.cast(db.Text),
        Notification.status,
        *([Notification.template_id] if by_template else []),
        func.count().label('count')
    ).filter(
        Notification.created_at >= get_local_timezone_midnight(now),
        Notification.service_id == service_id,
        Notification.key_type != KEY_TYPE_TEST
    ).group_by(
        Notification.notification_type,
        *([Notification.template_id] if by_template else []),
        Notification.status
    )

    all_stats_table = stats_for_7_days.union_all(stats_for_today).subquery()

    query = db.session.query(
        *([
            Template.name.label("template_name"),
            Template.is_precompiled_letter,
            all_stats_table.c.template_id
        ] if by_template else []),
        all_stats_table.c.notification_type,
        all_stats_table.c.status,
        func.cast(func.sum(all_stats_table.c.count), Integer).label('count'),
    )

    if by_template:
        query = query.filter(all_stats_table.c.template_id == Template.id)

    return query.group_by(
        *([Template.name, Template.is_precompiled_letter, all_stats_table.c.template_id] if by_template else []),
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

    return db.session.query(
        Notification.notification_type.label('notification_type'),
        func.count(Notification.id).label('total_send_attempts')
    ).filter(
        Notification.api_key_id == api_key_id,
    ).group_by(
        Notification.notification_type
    ).all()


def get_last_send_for_api_key(api_key_id):
    """
    SELECT max(created_at) as last_notification_created
    FROM notifications
    WHERE api_key_id = 'api_key_id'
    GROUP BY api_key_id;
    """

    return db.session.query(
        func.max(Notification.created_at).label('last_notification_created')
    ).filter(
        Notification.api_key_id == api_key_id
    ).group_by(
        Notification.api_key_id
    ).all()


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

    a = db.session.query(
        Notification.api_key_id,
        Notification.service_id,
        func.max(Notification.created_at).label('last_notification_created'),
        case([
            (Notification.notification_type == EMAIL_TYPE, func.count())
        ], else_=0).label('email_notifications'),
        case([
            (Notification.notification_type == SMS_TYPE, func.count())
        ], else_=0).label('sms_notifications')
    ).filter(
        Notification.created_at >= start_date,
        Notification.api_key_id is not None,
        Notification.key_type == KEY_TYPE_NORMAL
    ).group_by(
        Notification.api_key_id,
        Notification.service_id,
        Notification.notification_type
    ).subquery()

    b = db.session.query(
        a.c.api_key_id,
        a.c.service_id,
        func.max(a.c.last_notification_created).label('last_notification_created'),
        func.sum(a.c.email_notifications).label('email_notifications'),
        func.sum(a.c.sms_notifications).label('sms_notifications'),
        (func.sum(a.c.email_notifications) + func.sum(a.c.sms_notifications)).label('total_notifications')
    ).group_by(
        a.c.api_key_id,
        a.c.service_id
    ).subquery()

    return db.session.query(
        ApiKey.name,
        ApiKey.key_type,
        Service.name,
        b.c.api_key_id,
        b.c.service_id,
        b.c.last_notification_created,
        b.c.email_notifications,
        b.c.sms_notifications,
        b.c.total_notifications
    ).join(
        ApiKey, ApiKey.id == b.c.api_key_id
    ).join(
        Service, Service.id == b.c.service_id
    ).order_by(
        b.c.total_notifications.desc()
    ).limit(
        50
    ).all()


def fetch_notification_status_totals_for_all_services(start_date, end_date):
    stats = db.session.query(
        FactNotificationStatus.notification_type.label('notification_type'),
        FactNotificationStatus.notification_status.label('status'),
        FactNotificationStatus.key_type.label('key_type'),
        func.sum(FactNotificationStatus.notification_count).label('count')
    ).filter(
        FactNotificationStatus.bst_date >= start_date,
        FactNotificationStatus.bst_date <= end_date
    ).group_by(
        FactNotificationStatus.notification_type,
        FactNotificationStatus.notification_status,
        FactNotificationStatus.key_type,
    )
    today = get_local_timezone_midnight_in_utc(datetime.utcnow())
    if start_date <= datetime.utcnow().date() <= end_date:
        stats_for_today = db.session.query(
            Notification.notification_type.cast(db.Text).label('notification_type'),
            Notification.status,
            Notification.key_type,
            func.count().label('count')
        ).filter(
            Notification.created_at >= today
        ).group_by(
            Notification.notification_type.cast(db.Text),
            Notification.status,
            Notification.key_type,
        )
        all_stats_table = stats.union_all(stats_for_today).subquery()
        query = db.session.query(
            all_stats_table.c.notification_type,
            all_stats_table.c.status,
            all_stats_table.c.key_type,
            func.cast(func.sum(all_stats_table.c.count), Integer).label('count'),
        ).group_by(
            all_stats_table.c.notification_type,
            all_stats_table.c.status,
            all_stats_table.c.key_type,
        ).order_by(
            all_stats_table.c.notification_type
        )
    else:
        query = stats.order_by(
            FactNotificationStatus.notification_type
        )
    return query.all()


def fetch_notification_statuses_for_job(job_id):
    return db.session.query(
        FactNotificationStatus.notification_status.label('status'),
        func.sum(FactNotificationStatus.notification_count).label('count'),
    ).filter(
        FactNotificationStatus.job_id == job_id,
    ).group_by(
        FactNotificationStatus.notification_status
    ).all()


def fetch_stats_for_all_services_by_date_range(start_date, end_date, include_from_test_key=True):
    stats = db.session.query(
        FactNotificationStatus.service_id.label('service_id'),
        Service.name.label('name'),
        Service.restricted.label('restricted'),
        Service.research_mode.label('research_mode'),
        Service.active.label('active'),
        Service.created_at.label('created_at'),
        FactNotificationStatus.notification_type.label('notification_type'),
        FactNotificationStatus.notification_status.label('status'),
        func.sum(FactNotificationStatus.notification_count).label('count')
    ).filter(
        FactNotificationStatus.bst_date >= start_date,
        FactNotificationStatus.bst_date <= end_date,
        FactNotificationStatus.service_id == Service.id,
    ).group_by(
        FactNotificationStatus.service_id.label('service_id'),
        Service.name,
        Service.restricted,
        Service.research_mode,
        Service.active,
        Service.created_at,
        FactNotificationStatus.notification_type,
        FactNotificationStatus.notification_status,
    ).order_by(
        FactNotificationStatus.service_id,
        FactNotificationStatus.notification_type
    )
    if not include_from_test_key:
        stats = stats.filter(FactNotificationStatus.key_type != KEY_TYPE_TEST)

    if start_date <= datetime.utcnow().date() <= end_date:
        today = get_local_timezone_midnight_in_utc(datetime.utcnow())
        subquery = db.session.query(
            Notification.notification_type.cast(db.Text).label('notification_type'),
            Notification.status.label('status'),
            Notification.service_id.label('service_id'),
            func.count(Notification.id).label('count')
        ).filter(
            Notification.created_at >= today
        ).group_by(
            Notification.notification_type,
            Notification.status,
            Notification.service_id
        )
        if not include_from_test_key:
            subquery = subquery.filter(Notification.key_type != KEY_TYPE_TEST)
        subquery = subquery.subquery()

        stats_for_today = db.session.query(
            Service.id.label('service_id'),
            Service.name.label('name'),
            Service.restricted.label('restricted'),
            Service.research_mode.label('research_mode'),
            Service.active.label('active'),
            Service.created_at.label('created_at'),
            subquery.c.notification_type.label('notification_type'),
            subquery.c.status.label('status'),
            subquery.c.count.label('count')
        ).outerjoin(
            subquery,
            subquery.c.service_id == Service.id
        )

        all_stats_table = stats.union_all(stats_for_today).subquery()
        query = db.session.query(
            all_stats_table.c.service_id,
            all_stats_table.c.name,
            all_stats_table.c.restricted,
            all_stats_table.c.research_mode,
            all_stats_table.c.active,
            all_stats_table.c.created_at,
            all_stats_table.c.notification_type,
            all_stats_table.c.status,
            func.cast(func.sum(all_stats_table.c.count), Integer).label('count'),
        ).group_by(
            all_stats_table.c.service_id,
            all_stats_table.c.name,
            all_stats_table.c.restricted,
            all_stats_table.c.research_mode,
            all_stats_table.c.active,
            all_stats_table.c.created_at,
            all_stats_table.c.notification_type,
            all_stats_table.c.status,
        ).order_by(
            all_stats_table.c.name,
            all_stats_table.c.notification_type,
            all_stats_table.c.status
        )
    else:
        query = stats
    return query.all()


def fetch_monthly_template_usage_for_service(start_date, end_date, service_id):
    # services_dao.replaces dao_fetch_monthly_historical_usage_by_template_for_service
    stats = db.session.query(
        FactNotificationStatus.template_id.label('template_id'),
        Template.name.label('name'),
        Template.template_type.label('template_type'),
        Template.is_precompiled_letter.label('is_precompiled_letter'),
        extract('month', FactNotificationStatus.bst_date).label('month'),
        extract('year', FactNotificationStatus.bst_date).label('year'),
        func.sum(FactNotificationStatus.notification_count).label('count')
    ).join(
        Template, FactNotificationStatus.template_id == Template.id
    ).filter(
        FactNotificationStatus.service_id == service_id,
        FactNotificationStatus.bst_date >= start_date.strftime("%Y-%m-%d"),
        # This works only for timezones to the west of GMT
        FactNotificationStatus.bst_date < end_date.strftime("%Y-%m-%d"),
        FactNotificationStatus.key_type != KEY_TYPE_TEST,
        FactNotificationStatus.notification_status != NOTIFICATION_CANCELLED,
    ).group_by(
        FactNotificationStatus.template_id,
        Template.name,
        Template.template_type,
        Template.is_precompiled_letter,
        extract('month', FactNotificationStatus.bst_date).label('month'),
        extract('year', FactNotificationStatus.bst_date).label('year'),
    ).order_by(
        extract('year', FactNotificationStatus.bst_date),
        extract('month', FactNotificationStatus.bst_date),
        Template.name
    )

    if start_date <= datetime.utcnow() <= end_date:
        today = get_local_timezone_midnight_in_utc(datetime.utcnow())
        month = get_local_timezone_month_from_utc_column(Notification.created_at)

        stats_for_today = db.session.query(
            Notification.template_id.label('template_id'),
            Template.name.label('name'),
            Template.template_type.label('template_type'),
            Template.is_precompiled_letter.label('is_precompiled_letter'),
            extract('month', month).label('month'),
            extract('year', month).label('year'),
            func.count().label('count')
        ).join(
            Template, Notification.template_id == Template.id,
        ).filter(
            Notification.created_at >= today,
            Notification.service_id == service_id,
            Notification.key_type != KEY_TYPE_TEST,
            Notification.status != NOTIFICATION_CANCELLED
        ).group_by(
            Notification.template_id,
            Template.hidden,
            Template.name,
            Template.template_type,
            month
        )

        all_stats_table = stats.union_all(stats_for_today).subquery()
        query = db.session.query(
            all_stats_table.c.template_id,
            all_stats_table.c.name,
            all_stats_table.c.is_precompiled_letter,
            all_stats_table.c.template_type,
            func.cast(all_stats_table.c.month, Integer).label('month'),
            func.cast(all_stats_table.c.year, Integer).label('year'),
            func.cast(func.sum(all_stats_table.c.count), Integer).label('count'),
        ).group_by(
            all_stats_table.c.template_id,
            all_stats_table.c.name,
            all_stats_table.c.is_precompiled_letter,
            all_stats_table.c.template_type,
            all_stats_table.c.month,
            all_stats_table.c.year,
        ).order_by(
            all_stats_table.c.year,
            all_stats_table.c.month,
            all_stats_table.c.name
        )
    else:
        query = stats
    return query.all()


def get_total_sent_notifications_for_day_and_type(day, notification_type):
    result = db.session.query(
        func.sum(FactNotificationStatus.notification_count).label('count')
    ).filter(
        FactNotificationStatus.notification_type == notification_type,
        FactNotificationStatus.key_type != KEY_TYPE_TEST,
        FactNotificationStatus.bst_date == day,
    ).scalar()

    return result or 0


def fetch_monthly_notification_statuses_per_service(start_date, end_date):
    return db.session.query(
        func.date_trunc('month', FactNotificationStatus.bst_date).cast(Date).label('date_created'),
        Service.id.label('service_id'),
        Service.name.label('service_name'),
        FactNotificationStatus.notification_type,
        func.sum(case(
            [
                (FactNotificationStatus.notification_status == NOTIFICATION_SENDING,
                 FactNotificationStatus.notification_count)
            ],
            else_=0)).label('count_sending'),
        func.sum(case(
            [
                (FactNotificationStatus.notification_status == NOTIFICATION_DELIVERED,
                 FactNotificationStatus.notification_count)
            ],
            else_=0)).label('count_delivered'),
        func.sum(case(
            [
                (FactNotificationStatus.notification_status.in_([NOTIFICATION_TECHNICAL_FAILURE, NOTIFICATION_FAILED]),
                 FactNotificationStatus.notification_count)
            ],
            else_=0)).label('count_technical_failure'),
        func.sum(case(
            [
                (FactNotificationStatus.notification_status == NOTIFICATION_TEMPORARY_FAILURE,
                 FactNotificationStatus.notification_count)
            ],
            else_=0)).label('count_temporary_failure'),
        func.sum(case(
            [
                (FactNotificationStatus.notification_status == NOTIFICATION_PERMANENT_FAILURE,
                 FactNotificationStatus.notification_count)
            ],
            else_=0)).label('count_permanent_failure'),
        func.sum(case(
            [
                (FactNotificationStatus.notification_status == NOTIFICATION_SENT,
                 FactNotificationStatus.notification_count)
            ],
            else_=0)).label('count_sent'),
    ).join(
        Service, FactNotificationStatus.service_id == Service.id
    ).filter(
        FactNotificationStatus.notification_status != NOTIFICATION_CREATED,
        Service.active.is_(True),
        FactNotificationStatus.key_type != KEY_TYPE_TEST,
        Service.research_mode.is_(False),
        Service.restricted.is_(False),
        FactNotificationStatus.bst_date >= start_date,
        FactNotificationStatus.bst_date <= end_date,
    ).group_by(
        Service.id,
        Service.name,
        func.date_trunc('month', FactNotificationStatus.bst_date).cast(Date),
        FactNotificationStatus.notification_type,
    ).order_by(
        func.date_trunc('month', FactNotificationStatus.bst_date).cast(Date),
        Service.id,
        FactNotificationStatus.notification_type,
    ).all()
