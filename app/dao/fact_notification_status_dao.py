from datetime import datetime, timedelta, time

from flask import current_app
from notifications_utils.timezones import convert_local_timezone_to_utc
from sqlalchemy import case, delete, func, Date, select, union_all
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql.expression import literal
from sqlalchemy.types import DateTime, Integer

from app import db
from app.constants import (
    EMAIL_TYPE,
    KEY_TYPE_TEST,
    LETTER_TYPE,
    NOTIFICATION_CANCELLED,
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
    SMS_TYPE,
)
from app.models import (
    FactNotificationStatus,
    Notification,
    NotificationHistory,
    Service,
    Template,
)
from app.utils import (
    get_local_timezone_midnight_in_utc,
    midnight_n_days_ago,
    get_local_timezone_midnight,
)


def fetch_notification_status_for_day(
    process_day,
    service_id=None,
):
    start_date = convert_local_timezone_to_utc(datetime.combine(process_day, time.min))
    end_date = convert_local_timezone_to_utc(datetime.combine(process_day + timedelta(days=1), time.min))
    # use notification_history if process day is older than 7 days
    # this is useful if we need to rebuild the ft_billing table for a date older than 7 days ago.
    current_app.logger.info('Fetch ft_notification_status for {} to {}'.format(start_date, end_date))

    all_data_for_process_day = []
    service_ids = [x.id for x in db.session.scalars(select(Service)).all()]
    # for each service
    # for each notification type
    # query notifications for day
    # if no rows try notificationHistory
    for service_id in service_ids:
        for notification_type in [EMAIL_TYPE, SMS_TYPE, LETTER_TYPE]:
            data_for_service_and_type = _query_for_fact_status_data(
                table=Notification,
                start_date=start_date,
                end_date=end_date,
                notification_type=notification_type,
                service_id=service_id,
            )

            if not data_for_service_and_type:
                data_for_service_and_type = _query_for_fact_status_data(
                    table=NotificationHistory,
                    start_date=start_date,
                    end_date=end_date,
                    notification_type=notification_type,
                    service_id=service_id,
                )
            all_data_for_process_day.extend(data_for_service_and_type)

    return all_data_for_process_day


def _query_for_fact_status_data(
    table,
    start_date,
    end_date,
    notification_type,
    service_id,
):
    stmt = (
        select(
            table.template_id,
            table.service_id,
            func.coalesce(table.job_id, '00000000-0000-0000-0000-000000000000').label('job_id'),
            table.notification_type,
            table.key_type,
            table.status,
            table.status_reason,
            func.count().label('notification_count'),
        )
        .where(
            table.created_at >= start_date,
            table.created_at < end_date,
            table.notification_type == notification_type,
            table.service_id == service_id,
            table.key_type != KEY_TYPE_TEST,
        )
        .group_by(
            table.template_id,
            table.service_id,
            'job_id',
            table.notification_type,
            table.key_type,
            table.status,
            table.status_reason,
        )
    )

    return db.session.execute(stmt).all()


def update_fact_notification_status(
    data,
    process_day,
):
    stmt = delete(FactNotificationStatus).where(FactNotificationStatus.bst_date == process_day)
    db.session.execute(stmt)
    db.session.commit()

    insertion_values = [
        {
            'bst_date': process_day,
            'template_id': row.template_id,
            'service_id': row.service_id,
            'job_id': row.job_id,
            'notification_type': row.notification_type,
            'key_type': row.key_type,
            'notification_status': row.status,
            'status_reason': row.status_reason if row.status_reason else '',
            'notification_count': row.notification_count,
        }
        for row in data
    ]

    db.session.execute(insert(FactNotificationStatus), insertion_values)
    db.session.commit()


def fetch_notification_status_for_service_by_month(
    start_date,
    end_date,
    service_id,
):
    stmt = (
        select(
            func.date_trunc('month', FactNotificationStatus.bst_date).label('month'),
            FactNotificationStatus.notification_type,
            FactNotificationStatus.notification_status,
            func.sum(FactNotificationStatus.notification_count).label('count'),
        )
        .where(
            FactNotificationStatus.service_id == service_id,
            FactNotificationStatus.bst_date >= start_date.strftime('%Y-%m-%d'),
            # This works only for timezones to the west of GMT
            FactNotificationStatus.bst_date < end_date.strftime('%Y-%m-%d'),
            FactNotificationStatus.key_type != KEY_TYPE_TEST,
        )
        .group_by(
            func.date_trunc('month', FactNotificationStatus.bst_date).label('month'),
            FactNotificationStatus.notification_type,
            FactNotificationStatus.notification_status,
        )
    )

    return db.session.execute(stmt).all()


def fetch_delivered_notification_stats_by_month():
    stmt = (
        select(
            func.date_trunc('month', FactNotificationStatus.bst_date).cast(db.Text).label('month'),
            FactNotificationStatus.notification_type,
            func.sum(FactNotificationStatus.notification_count).label('count'),
        )
        .where(
            FactNotificationStatus.key_type != KEY_TYPE_TEST,
            FactNotificationStatus.notification_status.in_([NOTIFICATION_DELIVERED, NOTIFICATION_SENT]),
            FactNotificationStatus.bst_date >= '2020-04-01',
        )
        .group_by(
            func.date_trunc('month', FactNotificationStatus.bst_date),
            FactNotificationStatus.notification_type,
        )
        .order_by(
            func.date_trunc('month', FactNotificationStatus.bst_date).desc(),
            FactNotificationStatus.notification_type,
        )
    )

    return db.session.execute(stmt).all()


def fetch_notification_status_for_service_for_day(
    bst_day,
    service_id,
):
    stmt = (
        select(
            # return current month as a datetime so the data has the same shape as the ft_notification_status query
            literal(bst_day.replace(day=1), type_=DateTime).label('month'),
            Notification.notification_type,
            Notification.status.label('notification_status'),
            func.count().label('count'),
        )
        .where(
            Notification.created_at >= get_local_timezone_midnight_in_utc(bst_day),
            Notification.created_at < get_local_timezone_midnight_in_utc(bst_day + timedelta(days=1)),
            Notification.service_id == service_id,
            Notification.key_type != KEY_TYPE_TEST,
        )
        .group_by(Notification.notification_type, Notification.status)
    )

    return db.session.execute(stmt).all()


def fetch_notification_status_for_service_for_today_and_7_previous_days(
    service_id,
    by_template=False,
    limit_days=7,
):
    start_date = midnight_n_days_ago(limit_days)
    now = datetime.now()

    stats_for_7_days = select(
        FactNotificationStatus.notification_type.label('notification_type'),
        FactNotificationStatus.notification_status.label('status'),
        *([FactNotificationStatus.template_id.label('template_id')] if by_template else []),
        FactNotificationStatus.notification_count.label('count'),
    ).where(
        FactNotificationStatus.service_id == service_id,
        FactNotificationStatus.bst_date >= start_date,
        FactNotificationStatus.key_type != KEY_TYPE_TEST,
    )

    stats_for_today = (
        select(
            Notification.notification_type.cast(db.Text),
            Notification.status,
            *([Notification.template_id] if by_template else []),
            func.count().label('count'),
        )
        .where(
            Notification.created_at >= get_local_timezone_midnight(now),
            Notification.service_id == service_id,
            Notification.key_type != KEY_TYPE_TEST,
        )
        .group_by(
            Notification.notification_type, *([Notification.template_id] if by_template else []), Notification.status
        )
    )

    all_stats_table = union_all(stats_for_7_days, stats_for_today).subquery()

    stmt = select(
        *(
            [Template.name.label('template_name'), Template.is_precompiled_letter, all_stats_table.c.template_id]
            if by_template
            else []
        ),
        all_stats_table.c.notification_type,
        all_stats_table.c.status,
        func.cast(func.sum(all_stats_table.c.count), Integer).label('count'),
    )

    if by_template:
        stmt = stmt.where(all_stats_table.c.template_id == Template.id)

    stmt = stmt.group_by(
        *([Template.name, Template.is_precompiled_letter, all_stats_table.c.template_id] if by_template else []),
        all_stats_table.c.notification_type,
        all_stats_table.c.status,
    )

    return db.session.execute(stmt).all()


def fetch_notification_status_totals_for_all_services(
    start_date,
    end_date,
):
    stats = (
        select(
            FactNotificationStatus.notification_type.label('notification_type'),
            FactNotificationStatus.notification_status.label('status'),
            FactNotificationStatus.key_type.label('key_type'),
            func.sum(FactNotificationStatus.notification_count).label('count'),
        )
        .where(FactNotificationStatus.bst_date >= start_date, FactNotificationStatus.bst_date <= end_date)
        .group_by(
            FactNotificationStatus.notification_type,
            FactNotificationStatus.notification_status,
            FactNotificationStatus.key_type,
        )
    )

    today = get_local_timezone_midnight_in_utc(datetime.utcnow())

    if start_date <= datetime.utcnow().date() <= end_date:
        stats_for_today = (
            select(
                Notification.notification_type.cast(db.Text).label('notification_type'),
                Notification.status,
                Notification.key_type,
                func.count().label('count'),
            )
            .where(Notification.created_at >= today)
            .group_by(
                Notification.notification_type.cast(db.Text),
                Notification.status,
                Notification.key_type,
            )
        )

        all_stats_table = union_all(stats, stats_for_today).subquery()

        stmt = (
            select(
                all_stats_table.c.notification_type,
                all_stats_table.c.status,
                all_stats_table.c.key_type,
                func.cast(func.sum(all_stats_table.c.count), Integer).label('count'),
            )
            .group_by(
                all_stats_table.c.notification_type,
                all_stats_table.c.status,
                all_stats_table.c.key_type,
            )
            .order_by(all_stats_table.c.notification_type)
        )
    else:
        stmt = stats.order_by(FactNotificationStatus.notification_type)

    return db.session.execute(stmt).all()


def fetch_stats_for_all_services_by_date_range(
    start_date,
    end_date,
    include_from_test_key=True,
):
    stats = (
        select(
            FactNotificationStatus.service_id.label('service_id'),
            Service.name.label('name'),
            Service.restricted.label('restricted'),
            Service.research_mode.label('research_mode'),
            Service.active.label('active'),
            Service.created_at.label('created_at'),
            FactNotificationStatus.notification_type.label('notification_type'),
            FactNotificationStatus.notification_status.label('status'),
            func.sum(FactNotificationStatus.notification_count).label('count'),
        )
        .where(
            FactNotificationStatus.bst_date >= start_date,
            FactNotificationStatus.bst_date <= end_date,
            FactNotificationStatus.service_id == Service.id,
        )
        .group_by(
            FactNotificationStatus.service_id.label('service_id'),
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
        stats = stats.where(FactNotificationStatus.key_type != KEY_TYPE_TEST)

    if start_date <= datetime.utcnow().date() <= end_date:
        today = get_local_timezone_midnight_in_utc(datetime.utcnow())

        a = (
            select(
                Notification.notification_type.cast(db.Text).label('notification_type'),
                Notification.status.label('status'),
                Notification.service_id.label('service_id'),
                func.count(Notification.id).label('count'),
            )
            .where(Notification.created_at >= today)
            .group_by(Notification.notification_type, Notification.status, Notification.service_id)
        )

        if not include_from_test_key:
            a = a.where(Notification.key_type != KEY_TYPE_TEST)

        a = a.subquery()

        stats_for_today = select(
            Service.id.label('service_id'),
            Service.name.label('name'),
            Service.restricted.label('restricted'),
            Service.research_mode.label('research_mode'),
            Service.active.label('active'),
            Service.created_at.label('created_at'),
            a.c.notification_type.label('notification_type'),
            a.c.status.label('status'),
            a.c.count.label('count'),
        ).outerjoin(a, a.c.service_id == Service.id)

        all_stats_table = union_all(stats, stats_for_today).subquery()

        stmt = (
            select(
                all_stats_table.c.service_id,
                all_stats_table.c.name,
                all_stats_table.c.restricted,
                all_stats_table.c.research_mode,
                all_stats_table.c.active,
                all_stats_table.c.created_at,
                all_stats_table.c.notification_type,
                all_stats_table.c.status,
                func.cast(func.sum(all_stats_table.c.count), Integer).label('count'),
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
            .order_by(all_stats_table.c.name, all_stats_table.c.notification_type, all_stats_table.c.status)
        )
    else:
        stmt = stats

    return db.session.execute(stmt).all()


def fetch_template_usage_for_service_with_given_template(
    service_id,
    template_id,
    start_date=None,
    end_date=None,
):
    fns_filter = _get_fact_notification_status_filters(end_date, service_id, start_date, template_id)

    stats = (
        select(
            FactNotificationStatus.notification_status.label('status'),
            func.sum(FactNotificationStatus.notification_count).label('count'),
        )
        .join(Template, FactNotificationStatus.template_id == Template.id)
        .where(*fns_filter)
        .group_by(FactNotificationStatus.notification_status)
    )

    if _should_get_todays_stats(start_date, end_date):
        today = get_local_timezone_midnight_in_utc(datetime.utcnow())

        stats_for_today = (
            select(Notification.status.label('status'), func.count().label('count'))
            .join(
                Template,
                Notification.template_id == Template.id,
            )
            .where(
                Notification.created_at >= today,
                Notification.service_id == service_id,
                Notification.template_id == template_id,
                Notification.key_type != KEY_TYPE_TEST,
                Notification.status != NOTIFICATION_CANCELLED,
            )
            .group_by(
                Notification.status,
            )
        )

        all_stats_table = union_all(stats, stats_for_today).subquery()

        stmt = select(
            all_stats_table.c.status,
            func.cast(func.sum(all_stats_table.c.count), Integer).label('count'),
        ).group_by(
            all_stats_table.c.status,
        )
    else:
        stmt = stats

    return db.session.execute(stmt).all()


def fetch_notification_statuses_per_service_and_template_for_date(date):
    stmt = (
        select(
            FactNotificationStatus.service_id.label('service_id'),
            Service.name.label('service_name'),
            FactNotificationStatus.template_id.label('template_id'),
            Template.name.label('template_name'),
            FactNotificationStatus.notification_status.label('status'),
            FactNotificationStatus.status_reason.label('status_reason'),
            FactNotificationStatus.notification_count.label('count'),
            Template.template_type.label('channel_type'),
        )
        .join(Template, FactNotificationStatus.template_id == Template.id)
        .join(Service, FactNotificationStatus.service_id == Service.id)
        .where(
            FactNotificationStatus.key_type != KEY_TYPE_TEST,
            Service.research_mode.is_(False),
            FactNotificationStatus.bst_date == date.strftime('%Y-%m-%d'),
        )
    )

    return db.session.execute(stmt).all()


def get_total_sent_notifications_for_day_and_type(
    day,
    notification_type,
):
    stmt = select(func.sum(FactNotificationStatus.notification_count).label('count')).where(
        FactNotificationStatus.notification_type == notification_type,
        FactNotificationStatus.key_type != KEY_TYPE_TEST,
        FactNotificationStatus.bst_date == day,
    )

    return db.session.scalar(stmt) or 0


def fetch_monthly_notification_statuses_per_service(
    start_date,
    end_date,
):
    stmt = (
        select(
            func.date_trunc('month', FactNotificationStatus.bst_date).cast(Date).label('date_created'),
            Service.id.label('service_id'),
            Service.name.label('service_name'),
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
            ).label('count_sending'),
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
            ).label('count_delivered'),
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
            ).label('count_temporary_failure'),
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
            ).label('count_permanent_failure'),
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
            ).label('count_sent'),
        )
        .join(Service, FactNotificationStatus.service_id == Service.id)
        .where(
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
            func.date_trunc('month', FactNotificationStatus.bst_date).cast(Date),
            FactNotificationStatus.notification_type,
        )
        .order_by(
            func.date_trunc('month', FactNotificationStatus.bst_date).cast(Date),
            Service.id,
            FactNotificationStatus.notification_type,
        )
    )

    return db.session.execute(stmt).all()


def _get_fact_notification_status_filters(
    end_date,
    service_id,
    start_date,
    template_id,
):
    fns_filter = [
        FactNotificationStatus.service_id == service_id,
        FactNotificationStatus.template_id == template_id,
        FactNotificationStatus.key_type != KEY_TYPE_TEST,
        FactNotificationStatus.notification_status != NOTIFICATION_CANCELLED,
    ]
    if start_date:
        fns_filter.append(FactNotificationStatus.bst_date >= start_date.strftime('%Y-%m-%d'))
    if end_date:
        fns_filter.append(FactNotificationStatus.bst_date < end_date.strftime('%Y-%m-%d'))
    return fns_filter


def _should_get_todays_stats(
    start_date=None,
    end_date=None,
):
    current_time = datetime.utcnow().date()
    if not start_date and not end_date:
        return True

    if not start_date:
        return current_time <= end_date

    if not end_date:
        return start_date <= current_time

    return start_date <= current_time <= end_date
