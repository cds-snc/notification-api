import functools
import string
from datetime import datetime, timedelta

from flask import current_app
from itsdangerous import BadSignature
from notifications_utils.international_billing_rates import INTERNATIONAL_BILLING_RATES
from notifications_utils.recipients import (
    InvalidEmailError,
    try_validate_and_format_phone_number,
    validate_and_format_email_address,
)
from notifications_utils.statsd_decorators import statsd
from notifications_utils.timezones import (
    convert_local_timezone_to_utc,
    convert_utc_to_local_timezone,
)
from sqlalchemy import asc, desc, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import defer, joinedload
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql import functions, literal_column
from sqlalchemy.sql.expression import case
from werkzeug.datastructures import MultiDict

from app import create_uuid, db, signer_personalisation
from app.dao.dao_utils import transactional
from app.dao.date_util import get_query_date_based_on_retention_period
from app.errors import InvalidRequest
from app.models import (
    EMAIL_TYPE,
    KEY_TYPE_TEST,
    LETTER_TYPE,
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_HARD_BOUNCE,
    NOTIFICATION_PENDING,
    NOTIFICATION_PENDING_VIRUS_CHECK,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
    SMS_TYPE,
    Notification,
    NotificationHistory,
    Organisation,
    ScheduledNotification,
    Service,
    ServiceDataRetention,
)
from app.utils import escape_special_characters


@transactional
def _resign_notifications_chunk(chunk_offset: int, chunk_size: int, resign: bool, unsafe: bool) -> int:
    """Resign the _personalisation column of the notifications in a chunk of notifications with (potentially) a new key.

    Args:
        chunk_offset (int): start index of the chunk
        chunk_size (int): size of the chunk
        resign (bool): resign the personalisation
        unsafe (bool): ignore bad signatures

    Raises:
        e: BadSignature if the unsign step fails and unsafe is False.

    Returns:
        int: number of notifications resigned or needing to be resigned
    """
    rows = Notification.query.order_by(Notification.created_at).slice(chunk_offset, chunk_offset + chunk_size).all()
    current_app.logger.info(f"Processing chunk {chunk_offset} to {chunk_offset + len(rows) - 1}")

    rows_to_update = []
    for row in rows:
        old_signature = row._personalisation
        if old_signature:
            try:
                unsigned_personalisation = getattr(row, "personalisation")  # unsign the personalisation
            except BadSignature as e:
                if unsafe:
                    unsigned_personalisation = signer_personalisation.verify_unsafe(row._personalisation)
                else:
                    current_app.logger.warning(f"BadSignature for notification {row.id}: {e}")
                    raise e
        setattr(
            row, "personalisation", unsigned_personalisation
        )  # resigns the personalisation with (potentially) a new signing secret
        if old_signature != row._personalisation:
            rows_to_update.append(row)
        if not resign:
            row._personalisation = old_signature  # reset the signature to the old value

    if resign and len(rows_to_update) > 0:
        current_app.logger.info(f"Resigning {len(rows_to_update)} notifications")
        db.session.bulk_save_objects(rows)
    elif len(rows_to_update) > 0:
        current_app.logger.info(f"{len(rows_to_update)} notifications need resigning")

    return len(rows_to_update)


def resign_notifications(chunk_size: int, resign: bool, unsafe: bool = False) -> int:
    """Resign the _personalisation column of the notifications table with (potentially) a new key.

    Args:
        chunk_size (int): number of rows to update at once.
        resign (bool): resign the notifications.
        unsafe (bool, optional): resign regardless of whether the unsign step fails with a BadSignature. Defaults to False.
        max_update_size(int, -1): max number of rows to update at once, -1 for no limit. Defautls to -1.

    Returns:
        int: number of notifications that were resigned or need to be resigned.

    Raises:
        e: BadSignature if the unsign step fails and unsafe is False.
    """

    total_notifications = Notification.query.count()
    current_app.logger.info(f"Total of {total_notifications} notifications")
    num_old_signatures = 0

    for chunk_offset in range(0, total_notifications, chunk_size):
        num_old_signatures_in_chunk = _resign_notifications_chunk(chunk_offset, chunk_size, resign, unsafe)
        num_old_signatures += num_old_signatures_in_chunk

    if resign:
        current_app.logger.info(f"Overall, {num_old_signatures} notifications were resigned")
    else:
        current_app.logger.info(f"Overall, {num_old_signatures} notifications need resigning")
    return num_old_signatures


@statsd(namespace="dao")
def dao_get_last_template_usage(template_id, template_type, service_id):
    # By adding the service_id to the filter the performance of the query is greatly improved.
    # Using a max(Notification.created_at) is better than order by and limit one.
    # But the effort to change the endpoint to return a datetime only is more than the gain.
    return (
        Notification.query.filter(
            Notification.template_id == template_id,
            Notification.key_type != KEY_TYPE_TEST,
            Notification.notification_type == template_type,
            Notification.service_id == service_id,
        )
        .order_by(desc(Notification.created_at))
        .first()
    )


@statsd(namespace="dao")
@transactional
def dao_create_notification(notification):
    if not notification.id:
        # need to populate defaulted fields before we create the notification history object
        notification.id = create_uuid()
    if not notification.status:
        notification.status = NOTIFICATION_CREATED

    db.session.add(notification)


@statsd(namespace="dao")
@transactional
def bulk_insert_notifications(notifications):
    """
    Takes a list of models.Notifications and inserts or updates the DB
    with the list accordingly

    Parameters:
    ----------
    notifications: lof models.Notification

    Return:
    ------
    None
    """
    for notification in notifications:
        if not notification.id:
            notification.id = create_uuid()
        if not notification.status:
            notification.status = NOTIFICATION_CREATED

    # TODO: Add error handling (Redis queue?) for failed notifications
    return db.session.bulk_save_objects(notifications)


def _decide_permanent_temporary_failure(current_status, status):
    # Firetext will send pending, then send either succes or fail.
    # If we go from pending to delivered we need to set failure type as temporary-failure
    if current_status == NOTIFICATION_PENDING and status == NOTIFICATION_PERMANENT_FAILURE:
        status = NOTIFICATION_TEMPORARY_FAILURE
    return status


def country_records_delivery(phone_prefix):
    dlr = INTERNATIONAL_BILLING_RATES[phone_prefix]["attributes"]["dlr"]
    return dlr and dlr.lower() == "yes"


def _update_notification_status(
    notification,
    status,
    provider_response=None,
    bounce_response=None,
    feedback_reason=None,
    sms_total_message_price=None,
    sms_total_carrier_fee=None,
    sms_iso_country_code=None,
    sms_carrier_name=None,
    sms_message_encoding=None,
    sms_origination_phone_number=None,
):
    status = _decide_permanent_temporary_failure(current_status=notification.status, status=status)
    notification.status = status
    if provider_response:
        notification.provider_response = provider_response
    if bounce_response:
        notification.feedback_type = bounce_response.get("feedback_type")
        notification.feedback_subtype = bounce_response.get("feedback_subtype")
        notification.ses_feedback_id = bounce_response.get("ses_feedback_id")
        notification.ses_feedback_date = bounce_response.get("ses_feedback_date")
    if feedback_reason:
        notification.feedback_reason = feedback_reason

    notification.sms_total_message_price = sms_total_message_price
    notification.sms_total_carrier_fee = sms_total_carrier_fee
    notification.sms_iso_country_code = sms_iso_country_code
    notification.sms_carrier_name = sms_carrier_name
    notification.sms_message_encoding = sms_message_encoding
    notification.sms_origination_phone_number = sms_origination_phone_number

    dao_update_notification(notification)
    return notification


@transactional
def _update_notification_statuses(updates):
    for update in updates:
        notification = update.get("notification")
        bounce_response = update.get("bounce_response")
        provider_response = update.get("provider_response")
        feedback_reason = update.get("feedback_reason")

        final_status = _decide_permanent_temporary_failure(current_status=notification.status, status=update.get("new_status"))
        notification.status = final_status
        if provider_response:
            notification.provider_response = update.get("provider_response")
        if bounce_response:
            notification.feedback_type = bounce_response.get("feedback_type")
            notification.feedback_subtype = bounce_response.get("feedback_subtype")
            notification.ses_feedback_id = bounce_response.get("ses_feedback_id")
            notification.ses_feedback_date = bounce_response.get("ses_feedback_date")
        if feedback_reason:
            notification.feedback_reason = feedback_reason
    update_notification_statuses([update.get("notification") for update in updates])


@transactional
def update_notification_statuses(notifications):
    db.session.bulk_save_objects(notifications)


@statsd(namespace="dao")
@transactional
def update_notification_status_by_id(notification_id, status, sent_by=None, feedback_reason=None):
    notification = Notification.query.with_for_update().filter(Notification.id == notification_id).first()

    if not notification:
        current_app.logger.info("notification not found for id {} (update to status {})".format(notification_id, status))
        return None

    if notification.status not in {
        NOTIFICATION_CREATED,
        NOTIFICATION_SENDING,
        NOTIFICATION_PENDING,
        NOTIFICATION_SENT,
        NOTIFICATION_PENDING_VIRUS_CHECK,
    }:
        _duplicate_update_warning(notification, status)
        return None

    if notification.international and not country_records_delivery(notification.phone_prefix):
        return None
    if not notification.sent_by and sent_by:
        notification.sent_by = sent_by
    return _update_notification_status(notification=notification, status=status, feedback_reason=feedback_reason)


@statsd(namespace="dao")
@transactional
def update_notification_status_by_reference(reference, status):
    # this is used to update letters and emails
    notification = Notification.query.filter(Notification.reference == reference).first()

    if not notification:
        current_app.logger.error("notification not found for reference {} (update to {})".format(reference, status))
        return None

    if notification.status not in {NOTIFICATION_SENDING, NOTIFICATION_PENDING}:
        _duplicate_update_warning(notification, status)
        return None

    return _update_notification_status(notification=notification, status=status)


@statsd(namespace="dao")
@transactional
def dao_update_notification(notification):
    notification.updated_at = datetime.utcnow()
    db.session.add(notification)


@statsd(namespace="dao")
def get_notification_for_job(service_id, job_id, notification_id):
    return Notification.query.filter_by(service_id=service_id, job_id=job_id, id=notification_id).one()


@statsd(namespace="dao")
def get_notifications_for_job(service_id, job_id, filter_dict=None, page=1, page_size=None):
    if page_size is None:
        page_size = current_app.config["PAGE_SIZE"]
    query = Notification.query.filter_by(service_id=service_id, job_id=job_id)
    query = _filter_query(query, filter_dict)
    return query.order_by(asc(Notification.job_row_number)).paginate(page=page, per_page=page_size)


@statsd(namespace="dao")
def get_notification_count_for_job(service_id, job_id):
    return Notification.query.filter_by(service_id=service_id, job_id=job_id).count()


@statsd(namespace="dao")
def get_notification_with_personalisation(service_id, notification_id, key_type):
    filter_dict = {"service_id": service_id, "id": notification_id}
    if key_type:
        filter_dict["key_type"] = key_type

    try:
        return Notification.query.filter_by(**filter_dict).options(joinedload("template")).one()
    except NoResultFound:
        current_app.logger.warning(f"Failed to get notification with filter: {filter_dict}")
        return None


@statsd(namespace="dao")
def get_notification_by_id(notification_id, service_id=None, _raise=False) -> Notification:
    filters = [Notification.id == notification_id]
    if service_id:
        filters.append(Notification.service_id == service_id)
    query = db.on_reader().query(Notification).filter(*filters)
    return query.one() if _raise else query.first()


def get_notifications(filter_dict=None):
    return _filter_query(Notification.query, filter_dict=filter_dict)


@statsd(namespace="dao")
def get_notifications_for_service(
    service_id,
    filter_dict=None,
    page=1,
    page_size=None,
    count_pages=True,
    limit_days=None,
    key_type=None,
    personalisation=False,
    include_jobs=False,
    include_from_test_key=False,
    older_than=None,
    client_reference=None,
    include_one_off=True,
    format_for_csv=False,
):
    if page_size is None:
        page_size = current_app.config["PAGE_SIZE"]

    filters = [Notification.service_id == service_id]

    if limit_days is not None:
        filters.append(Notification.created_at > get_query_date_based_on_retention_period(limit_days))

    if older_than is not None:
        older_than_created_at = db.session.query(Notification.created_at).filter(Notification.id == older_than).as_scalar()
        filters.append(Notification.created_at < older_than_created_at)

    if not include_jobs:
        filters.append(Notification.job_id == None)  # noqa

    if not include_one_off:
        filters.append(Notification.created_by_id == None)  # noqa

    if key_type is not None:
        filters.append(Notification.key_type == key_type)
    elif not include_from_test_key:
        filters.append(Notification.key_type != KEY_TYPE_TEST)

    if client_reference is not None:
        filters.append(Notification.client_reference == client_reference)

    query = Notification.query.filter(*filters)
    query = _filter_query(query, filter_dict)
    if personalisation:
        query = query.options(joinedload("template"))
    else:
        # this field is not used and it can contain a lot of data
        query = query.options(defer("_personalisation"))

    if format_for_csv:
        # do an explicit join on the template, job, and created_by tables so that we won't
        # do a separate query for each notification to get the template, job, and created_by
        # when the csv data is being generated
        query = query.options(
            joinedload(Notification.template), joinedload(Notification.job), joinedload(Notification.created_by)
        )

    return query.order_by(desc(Notification.created_at)).paginate(page=page, per_page=page_size, count=count_pages)


def _filter_query(query, filter_dict=None):
    if filter_dict is None:
        return query

    multidict = MultiDict(filter_dict)

    # filter by status
    statuses = multidict.getlist("status")
    if statuses:
        statuses = Notification.substitute_status(statuses)
        query = query.filter(Notification.status.in_(statuses))

    # filter by template
    template_types = multidict.getlist("template_type")
    if template_types:
        query = query.filter(Notification.notification_type.in_(template_types))

    return query


@statsd(namespace="dao")
def delete_notifications_older_than_retention_by_type(notification_type, qry_limit=10000):
    current_app.logger.info("Deleting {} notifications for services with flexible data retention".format(notification_type))

    flexible_data_retention = ServiceDataRetention.query.filter(ServiceDataRetention.notification_type == notification_type).all()
    deleted = 0
    for f in flexible_data_retention:
        days_of_retention = get_query_date_based_on_retention_period(f.days_of_retention)

        insert_update_notification_history(notification_type, days_of_retention, f.service_id)

        current_app.logger.info(
            "Deleting {} notifications for service id: {} uptil {} retention_days {}".format(
                notification_type, f.service_id, days_of_retention, f.days_of_retention
            )
        )
        deleted += _delete_notifications(notification_type, days_of_retention, f.service_id, qry_limit)

    current_app.logger.info("Deleting {} notifications for services without flexible data retention".format(notification_type))

    seven_days_ago = get_query_date_based_on_retention_period(7)
    services_with_data_retention = [x.service_id for x in flexible_data_retention]
    service_ids_to_purge = db.session.query(Service.id).filter(Service.id.notin_(services_with_data_retention)).all()

    for row in service_ids_to_purge:
        service_id = row._mapping["id"]
        insert_update_notification_history(notification_type, seven_days_ago, service_id)
        current_app.logger.info(
            "Deleting {} notifications for service id: {} uptil {} for 7days".format(
                notification_type, service_id, seven_days_ago
            )
        )
        deleted += _delete_notifications(notification_type, seven_days_ago, service_id, qry_limit)

    current_app.logger.info("Finished deleting {} notifications".format(notification_type))

    return deleted


def _delete_notifications(notification_type, date_to_delete_from, service_id, query_limit):
    subquery = (
        db.session.query(Notification.id)
        .join(NotificationHistory, NotificationHistory.id == Notification.id)
        .filter(
            Notification.notification_type == notification_type,
            Notification.service_id == service_id,
            Notification.created_at < date_to_delete_from,
        )
        .limit(query_limit)
        .subquery()
    )

    deleted = _delete_for_query(subquery)

    subquery_for_test_keys = (
        db.session.query(Notification.id)
        .filter(
            Notification.notification_type == notification_type,
            Notification.service_id == service_id,
            Notification.created_at < date_to_delete_from,
            Notification.key_type == KEY_TYPE_TEST,
        )
        .limit(query_limit)
        .subquery()
    )

    deleted += _delete_for_query(subquery_for_test_keys)

    return deleted


def _delete_for_query(subquery):
    number_deleted = db.session.query(Notification).filter(Notification.id.in_(subquery)).delete(synchronize_session="fetch")
    deleted = number_deleted
    db.session.commit()
    while number_deleted > 0:
        number_deleted = db.session.query(Notification).filter(Notification.id.in_(subquery)).delete(synchronize_session="fetch")
        deleted += number_deleted
        db.session.commit()
    return deleted


def insert_update_notification_history(notification_type, date_to_delete_from, service_id):
    notifications = db.session.query(*[literal_column(x.name) for x in NotificationHistory.__table__.c]).filter(
        Notification.notification_type == notification_type,
        Notification.service_id == service_id,
        Notification.created_at < date_to_delete_from,
        Notification.key_type != KEY_TYPE_TEST,
    )
    stmt = insert(NotificationHistory).from_select(NotificationHistory.__table__.c, notifications)

    stmt = stmt.on_conflict_do_update(
        constraint="notification_history_pkey",
        set_={
            "notification_status": stmt.excluded.status,
            "reference": stmt.excluded.reference,
            "billable_units": stmt.excluded.billable_units,
            "updated_at": stmt.excluded.updated_at,
            "sent_at": stmt.excluded.sent_at,
            "sent_by": stmt.excluded.sent_by,
        },
    )
    db.session.connection().execute(stmt)
    db.session.commit()


@statsd(namespace="dao")
@transactional
def dao_delete_notifications_by_id(notification_id):
    db.session.query(Notification).filter(Notification.id == notification_id).delete(synchronize_session="fetch")


def _timeout_notifications(current_statuses, new_status, timeout_start, updated_at):
    notifications = Notification.query.filter(
        Notification.created_at < timeout_start,
        Notification.status.in_(current_statuses),
        Notification.notification_type != LETTER_TYPE,
    ).all()
    Notification.query.filter(
        Notification.created_at < timeout_start,
        Notification.status.in_(current_statuses),
        Notification.notification_type != LETTER_TYPE,
    ).update({"status": new_status, "updated_at": updated_at}, synchronize_session=False)
    return notifications


def dao_timeout_notifications(timeout_period_in_seconds):
    """
    Timeout SMS and email notifications by the following rules:

    we never sent the notification to the provider for some reason
        created -> technical-failure

    the notification was sent to the provider but there was not a delivery receipt
        sending -> temporary-failure
        pending -> temporary-failure

    Letter notifications are not timed out
    """
    timeout_start = datetime.utcnow() - timedelta(seconds=timeout_period_in_seconds)
    updated_at = datetime.utcnow()
    timeout = functools.partial(_timeout_notifications, timeout_start=timeout_start, updated_at=updated_at)

    # Notifications still in created status are marked with a technical-failure:
    technical_failure_notifications = timeout([NOTIFICATION_CREATED], NOTIFICATION_TECHNICAL_FAILURE)

    # Notifications still in sending or pending status are marked with a temporary-failure:
    temporary_failure_notifications = timeout([NOTIFICATION_SENDING, NOTIFICATION_PENDING], NOTIFICATION_TEMPORARY_FAILURE)

    db.session.commit()

    return technical_failure_notifications, temporary_failure_notifications


def is_delivery_slow_for_provider(
    created_at,
    provider,
    threshold,
    delivery_time,
):
    count = (
        db.session.query(
            case(
                [
                    (
                        Notification.status == NOTIFICATION_DELIVERED,
                        (Notification.updated_at - Notification.sent_at) >= delivery_time,
                    )
                ],
                else_=(datetime.utcnow() - Notification.sent_at) >= delivery_time,
            ).label("slow"),
            func.count(),
        )
        .filter(
            Notification.created_at >= created_at,
            Notification.sent_at.isnot(None),
            Notification.status.in_([NOTIFICATION_DELIVERED, NOTIFICATION_PENDING, NOTIFICATION_SENDING]),
            Notification.sent_by == provider,
            Notification.key_type != KEY_TYPE_TEST,
        )
        .group_by("slow")
        .all()
    )

    counts = {c[0]: c[1] for c in count}
    total_notifications = sum(counts.values())
    slow_notifications = counts.get(True, 0)

    if total_notifications:
        current_app.logger.info(
            "Slow delivery notifications count for provider {}: {} out of {}. Ratio {}".format(
                provider,
                slow_notifications,
                total_notifications,
                slow_notifications / total_notifications,
            )
        )
        return slow_notifications / total_notifications >= threshold
    else:
        return False


@statsd(namespace="dao")
@transactional
def dao_update_notifications_by_reference(references, update_dict):
    updated_count = Notification.query.filter(Notification.reference.in_(references)).update(
        update_dict, synchronize_session=False
    )

    updated_history_count = 0
    if updated_count != len(references):
        updated_history_count = NotificationHistory.query.filter(NotificationHistory.reference.in_(references)).update(
            update_dict, synchronize_session=False
        )

    return updated_count, updated_history_count


@statsd(namespace="dao")
def dao_get_notifications_by_to_field(service_id, search_term, notification_type=None, statuses=None):
    if notification_type is None:
        notification_type = guess_notification_type(search_term)

    if notification_type == SMS_TYPE:
        normalised = try_validate_and_format_phone_number(search_term)

        for character in {"(", ")", " ", "-"}:
            normalised = normalised.replace(character, "")

        normalised = normalised.lstrip("+0")

    elif notification_type == EMAIL_TYPE:
        try:
            normalised = validate_and_format_email_address(search_term)
        except InvalidEmailError:
            normalised = search_term.lower()

    else:
        raise InvalidRequest("Only email and SMS can use search by recipient", 400)

    normalised = escape_special_characters(normalised)

    filters = [
        Notification.service_id == service_id,
        Notification.normalised_to.like("%{}%".format(normalised)),
        Notification.key_type != KEY_TYPE_TEST,
    ]

    if statuses:
        filters.append(Notification.status.in_(statuses))
    if notification_type:
        filters.append(Notification.notification_type == notification_type)

    results = db.session.query(Notification).filter(*filters).order_by(desc(Notification.created_at)).all()
    return results


@statsd(namespace="dao")
def dao_get_notification_by_reference(reference):
    return db.on_reader().query(Notification).filter(Notification.reference == reference).one()


@statsd(namespace="dao")
def dao_get_notification_history_by_reference(reference):
    try:
        # This try except is necessary because in test keys and research mode does not create notification history.
        # Otherwise we could just search for the NotificationHistory object
        return Notification.query.filter(Notification.reference == reference).one()
    except NoResultFound:
        return NotificationHistory.query.filter(NotificationHistory.reference == reference).one()


@statsd(namespace="dao")
def dao_get_notifications_by_references(references):
    results = Notification.query.filter(Notification.reference.in_(references)).all()

    if not results:
        raise NoResultFound(f"No notifications found for reference_ids {", ".join(references)}")
    return results


@statsd(namespace="dao")
def dao_created_scheduled_notification(scheduled_notification):
    db.session.add(scheduled_notification)
    db.session.commit()


@statsd(namespace="dao")
def dao_get_scheduled_notifications():
    notifications = (
        Notification.query.join(ScheduledNotification)
        .filter(
            ScheduledNotification.scheduled_for < datetime.utcnow(),
            ScheduledNotification.pending,
        )
        .all()
    )

    return notifications


def set_scheduled_notification_to_processed(notification_id):
    db.session.query(ScheduledNotification).filter(ScheduledNotification.notification_id == notification_id).update(
        {"pending": False}
    )
    db.session.commit()


def dao_get_total_notifications_sent_per_day_for_performance_platform(start_date, end_date):
    """
    SELECT
    count(notification_history),
    coalesce(sum(CASE WHEN sent_at - created_at <= interval '10 seconds' THEN 1 ELSE 0 END), 0)
    FROM notification_history
    WHERE
    created_at > 'START DATE' AND
    created_at < 'END DATE' AND
    api_key_id IS NOT NULL AND
    key_type != 'test' AND
    notification_type != 'letter';
    """
    under_10_secs = Notification.sent_at - Notification.created_at <= timedelta(seconds=10)
    sum_column = functions.coalesce(functions.sum(case([(under_10_secs, 1)], else_=0)), 0)

    return (
        db.session.query(
            func.count(Notification.id).label("messages_total"),
            sum_column.label("messages_within_10_secs"),
        )
        .filter(
            Notification.created_at >= start_date,
            Notification.created_at < end_date,
            Notification.api_key_id.isnot(None),
            Notification.key_type != KEY_TYPE_TEST,
            Notification.notification_type != LETTER_TYPE,
        )
        .one()
    )


@statsd(namespace="dao")
def get_latest_sent_notification_for_job(job_id):
    return Notification.query.filter(Notification.job_id == job_id).order_by(Notification.updated_at.desc()).limit(1).first()


@statsd(namespace="dao")
def dao_get_last_notification_added_for_job_id(job_id):
    last_notification_added = (
        Notification.query.filter(Notification.job_id == job_id).order_by(Notification.job_row_number.desc()).first()
    )

    return last_notification_added


def notifications_not_yet_sent(should_be_sending_after_seconds, notification_type):
    older_than_date = datetime.utcnow() - timedelta(seconds=should_be_sending_after_seconds)

    notifications = Notification.query.filter(
        Notification.created_at <= older_than_date,
        Notification.notification_type == notification_type,
        Notification.status == NOTIFICATION_CREATED,
    ).all()
    return notifications


def dao_old_letters_with_created_status():
    yesterday_bst = convert_utc_to_local_timezone(datetime.utcnow()) - timedelta(days=1)
    last_processing_deadline = yesterday_bst.replace(hour=17, minute=30, second=0, microsecond=0)

    notifications = (
        Notification.query.filter(
            Notification.updated_at < convert_local_timezone_to_utc(last_processing_deadline),
            Notification.notification_type == LETTER_TYPE,
            Notification.status == NOTIFICATION_CREATED,
        )
        .order_by(Notification.updated_at)
        .all()
    )
    return notifications


def dao_precompiled_letters_still_pending_virus_check():
    ninety_minutes_ago = datetime.utcnow() - timedelta(seconds=5400)

    notifications = (
        Notification.query.filter(
            Notification.created_at < ninety_minutes_ago,
            Notification.status == NOTIFICATION_PENDING_VIRUS_CHECK,
        )
        .order_by(Notification.created_at)
        .all()
    )
    return notifications


def guess_notification_type(search_term):
    if set(search_term) & set(string.ascii_letters + "@"):
        return EMAIL_TYPE
    else:
        return SMS_TYPE


def _duplicate_update_warning(notification, status):
    current_app.logger.info(
        (
            "Duplicate callback received. Notification id {id} received a status update to {new_status}"
            "{time_diff} after being set to {old_status}. {type} sent by {sent_by}"
        ).format(
            id=notification.id,
            old_status=notification.status,
            new_status=status,
            time_diff=datetime.utcnow() - (notification.updated_at or notification.created_at),
            type=notification.notification_type,
            sent_by=notification.sent_by,
        )
    )


def send_method_stats_by_service(start_time, end_time):
    return (
        db.session.query(
            Service.id.label("service_id"),
            Service.name.label("service_name"),
            Organisation.name.label("organisation_name"),
            NotificationHistory.notification_type,
            case([(NotificationHistory.api_key_id.isnot(None), "api")], else_="admin").label("send_method"),
            func.count().label("total_notifications"),
        )
        .join(Service, Service.id == NotificationHistory.service_id)
        .join(Organisation, Organisation.id == Service.organisation_id)
        .filter(
            NotificationHistory.status.in_([NOTIFICATION_DELIVERED, NOTIFICATION_SENT]),
            NotificationHistory.key_type != KEY_TYPE_TEST,
            NotificationHistory.created_at >= start_time,
            NotificationHistory.created_at <= end_time,
        )
        .group_by(
            Service.id,
            Service.name,
            Organisation.name,
            NotificationHistory.notification_type,
            case([(NotificationHistory.api_key_id.isnot(None), "api")], else_="admin"),
        )
        .all()
    )


@statsd(namespace="dao")
@transactional
def overall_bounce_rate_for_day(min_emails_sent=1000, default_time=datetime.utcnow()):
    """
    This function returns the bounce rate for all services for the last 24 hours.
    The bounce rate is calculated by dividing the number of hard bounces by the total number of emails sent.
    The bounce rate is returned as a percentage.

    :param min_emails_sent: the minimum number of emails sent to calculate the bounce rate for
    :param default_time: the time to calculate the bounce rate for
    :return: a list of tuple of the service_id, total number of email, # of hard bounces and the bounce rate
    """
    twenty_four_hours_ago = default_time - timedelta(hours=24)
    query = (
        db.session.query(
            Notification.service_id.label("service_id"),
            func.count(Notification.id).label("total_emails"),
            func.count().filter(Notification.feedback_type == NOTIFICATION_HARD_BOUNCE).label("hard_bounces"),
        )
        .filter(Notification.created_at.between(twenty_four_hours_ago, default_time))  # this value is the `[bounce-rate-window]`
        .group_by(Notification.service_id)
        .having(
            func.count(Notification.id) >= min_emails_sent
        )  # -- this value is the `[bounce-rate-warning-notification-volume-minimum]`
        .subquery()
    )
    data = db.session.query(query, (100 * query.c.hard_bounces / query.c.total_emails).label("bounce_rate")).all()
    return data


@statsd(namespace="dao")
@transactional
def service_bounce_rate_for_day(service_id, min_emails_sent=1000, default_time=datetime.utcnow()):
    """
    This function returns the bounce rate for a single services for the last 24 hours.
    The bounce rate is calculated by dividing the number of hard bounces by the total number of emails sent.
    The bounce rate is returned as a percentage.

    :param service_id: the service id to calculate the bounce rate for
    :param min_emails_sent: the minimum number of emails sent to calculate the bounce rate for
    :param default_time: the time to calculate the bounce rate for
    :return: a tuple of the total number of emails sent, # of bounced emails and the bounce rate or None if not enough emails
    """
    twenty_four_hours_ago = default_time - timedelta(hours=24)
    query = (
        db.session.query(
            func.count(Notification.id).label("total_emails"),
            func.count().filter(Notification.feedback_type == NOTIFICATION_HARD_BOUNCE).label("hard_bounces"),
        )
        .filter(Notification.created_at.between(twenty_four_hours_ago, default_time))  # this value is the `[bounce-rate-window]`
        .filter(Notification.service_id == service_id)
        .having(
            func.count(Notification.id) >= min_emails_sent
        )  # -- this value is the `[bounce-rate-warning-notification-volume-minimum]`
        .subquery()
    )
    data = db.session.query(query, (100 * query.c.hard_bounces / query.c.total_emails).label("bounce_rate")).first()
    return data


@statsd(namespace="dao")
@transactional
def total_notifications_grouped_by_hour(service_id, default_time=datetime.utcnow(), interval: int = 24):
    twenty_four_hours_ago = default_time - timedelta(hours=interval)
    query = (
        db.session.query(
            func.date_trunc("hour", Notification.created_at).label("hour"),
            func.count(Notification.id).label("total_notifications"),
        )
        .filter(Notification.created_at.between(twenty_four_hours_ago, default_time))
        .filter(Notification.service_id == service_id)
        .filter(Notification.notification_type == EMAIL_TYPE)
        .group_by(func.date_trunc("hour", Notification.created_at))
        .order_by(func.date_trunc("hour", Notification.created_at))
    )
    return query.all()


@statsd(namespace="dao")
@transactional
def total_hard_bounces_grouped_by_hour(service_id, default_time=datetime.utcnow(), interval: int = 24):
    twenty_four_hours_ago = default_time - timedelta(hours=interval)
    query = (
        db.session.query(
            func.date_trunc("hour", Notification.created_at).label("hour"),
            func.count(Notification.id).label("total_notifications"),
        )
        .filter(Notification.created_at.between(twenty_four_hours_ago, default_time))
        .filter(Notification.service_id == service_id)
        .filter(Notification.notification_type == EMAIL_TYPE)
        .filter(Notification.feedback_type == NOTIFICATION_HARD_BOUNCE)
        .group_by(func.date_trunc("hour", Notification.created_at))
        .order_by(func.date_trunc("hour", Notification.created_at))
    )
    return query.all()
