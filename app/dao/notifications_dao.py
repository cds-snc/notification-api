import functools
import string
import uuid
from datetime import (
    datetime,
    timedelta,
)

from botocore.exceptions import ClientError
from flask import current_app
from notifications_utils.international_billing_rates import INTERNATIONAL_BILLING_RATES
from notifications_utils.recipients import (
    validate_and_format_email_address,
    InvalidEmailError,
    try_validate_and_format_phone_number
)
from notifications_utils.statsd_decorators import statsd
from notifications_utils.timezones import convert_local_timezone_to_utc, convert_utc_to_local_timezone
from sqlalchemy import asc, desc, func, select, update
from sqlalchemy.exc import ArgumentError
from sqlalchemy.engine.row import Row
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql import functions, text
from sqlalchemy.sql.expression import case
from sqlalchemy.dialects.postgresql import insert
from werkzeug.datastructures import MultiDict

from app import db, create_uuid
from app.aws.s3 import remove_s3_object, get_s3_bucket_objects
from app.dao.dao_utils import transactional
from app.errors import InvalidRequest
from app.feature_flags import is_feature_enabled, FeatureFlag
from app.letters.utils import LETTERS_PDF_FILE_LOCATION_STRUCTURE
from app.models import (
    Notification,
    NotificationHistory,
    ScheduledNotification,
    KEY_TYPE_TEST,
    LETTER_TYPE,
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_SENDING,
    NOTIFICATION_PENDING,
    NOTIFICATION_PENDING_VIRUS_CHECK,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENT,
    NOTIFICATION_PREFERENCES_DECLINED,
    SMS_TYPE,
    EMAIL_TYPE,
    ServiceDataRetention,
    Service
)
from app.utils import get_local_timezone_midnight_in_utc
from app.utils import midnight_n_days_ago, escape_special_characters

TRANSIENT_STATUSES = (
    NOTIFICATION_CREATED,
    NOTIFICATION_SENDING,
    NOTIFICATION_PENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_PENDING_VIRUS_CHECK,
    NOTIFICATION_TEMPORARY_FAILURE
)

FINAL_STATUS_STATES = (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_PREFERENCES_DECLINED,
)


@statsd(namespace="dao")
def dao_get_last_template_usage(template_id, template_type, service_id):
    # By adding the service_id to the filter the performance of the query is greatly improved.
    # Using a max(Notification.created_at) is better than order by and limit one.
    # But the effort to change the endpoint to return a datetime only is more than the gain.
    return Notification.query.filter(
        Notification.template_id == template_id,
        Notification.key_type != KEY_TYPE_TEST,
        Notification.notification_type == template_type,
        Notification.service_id == service_id
    ).order_by(
        desc(Notification.created_at)
    ).first()


@statsd(namespace="dao")
@transactional
def dao_create_notification(notification):
    if not notification.id:
        # need to populate defaulted fields before we create the notification history object
        notification.id = create_uuid()
    if not notification.status:
        notification.status = NOTIFICATION_CREATED

    db.session.add(notification)


def _decide_permanent_temporary_failure(current_status, status):
    # Firetext will send pending, then send either succes or fail.
    # If we go from pending to delivered we need to set failure type as temporary-failure
    if current_status == NOTIFICATION_PENDING and status == NOTIFICATION_PERMANENT_FAILURE:
        status = NOTIFICATION_TEMPORARY_FAILURE
    return status


def country_records_delivery(phone_prefix):
    dlr = INTERNATIONAL_BILLING_RATES[phone_prefix]['attributes']['dlr']
    return dlr and dlr.lower() == 'yes'


def _get_notification_status_update_statement(notification_id: str, incoming_status: str, **kwargs):
    """
    Generates an update statement for the given notification id and status.
    Preserves status order and ensures a transient status will not override a final status.
    :param notification_id: String value of notification uuid to be updated
    :param status: String value of the status the given notification will attempt to update to
    :return: An update statement to be executed, or None
    """
    notification = db.session.get(Notification, notification_id)
    if notification is None:
        current_app.logger.error('No notification found when attempting to update status for notification %s',
                                 notification_id)
        return None

    current_status = notification.status
    incoming_status = _decide_permanent_temporary_failure(current_status=current_status, status=incoming_status)

    # do not update if the incoming status happens before the current status
    if incoming_status in TRANSIENT_STATUSES and current_status in TRANSIENT_STATUSES:
        if TRANSIENT_STATUSES.index(incoming_status) < TRANSIENT_STATUSES.index(current_status):
            current_app.logger.warning(
                'An erroneous attempt was made to transition notification id %s from %s to %s',
                notification_id,
                current_status,
                incoming_status
            )
            return None

    # add status to values dict if it doesn't have anything
    if len(kwargs) < 1:
        kwargs['status'] = incoming_status
    elif incoming_status == NOTIFICATION_TEMPORARY_FAILURE:
        kwargs['status'] = NOTIFICATION_TEMPORARY_FAILURE

    kwargs['updated_at'] = datetime.utcnow()

    # when updating make sure notification is not in final state via query
    update_statement = (
        update(Notification)
        .where(
            db.and_(
                Notification.id == notification_id,
                Notification.status.not_in(FINAL_STATUS_STATES)
            )
        )
        .values(kwargs)
    )

    return update_statement


def _update_notification_status(notification, status):
    """
    Update the notification status if it should be updated.
    """
    if not (status in TRANSIENT_STATUSES or status in FINAL_STATUS_STATES):
        current_app.logger.error(
            'Attempting to update notification %s to a status that does not exist %s', notification.id, status
        )
        return notification

    update_statement = _get_notification_status_update_statement(notification.id, status)

    try:
        db.session.execute(update_statement)
        db.session.commit()
    except NoResultFound as e:
        current_app.logger.warning(
            'No result found when attempting to update notification %s to status %s - The exception: %s',
            notification.id, status, e
        )
        return notification
    except ArgumentError as e:
        current_app.logger.warning(
            'Cannot update notification %s to status %s - exception: %s',
            notification.id, status, e
        )
        return notification
    except Exception as e:
        current_app.logger.error(
            'An error occured when attempting to update notification %s to status %s - The exception %s',
            notification.id, status, e
        )
        return notification

    return db.session.get(Notification, notification.id)


@statsd(namespace="dao")
@transactional
def update_notification_status_by_id(
        notification_id: uuid,
        status: str,
        sent_by: str = None,
        status_reason: str = None,
        current_status: str = None
) -> Notification:

    notification_query = Notification.query.with_for_update().filter(Notification.id == notification_id)
    if current_status is not None:
        notification_query.filter(Notification.status == current_status)

    notification = notification_query.first()
    if notification is None:
        current_app.logger.info(
            'notification not found for id %s (update to status %s)',
            notification_id,
            status
        )
        return None

    if notification.status not in TRANSIENT_STATUSES:
        duplicate_update_warning(notification, status)
        return None

    if notification.international and not country_records_delivery(notification.phone_prefix):
        return None

    if not notification.sent_by and sent_by:
        notification.sent_by = sent_by

    if is_feature_enabled(FeatureFlag.NOTIFICATION_FAILURE_REASON_ENABLED) and status_reason:
        notification.status_reason = status_reason

    return dao_update_notification_by_id(
        notification_id=notification.id,
        status=status,
        status_reason=notification.status_reason,
        sent_by=notification.sent_by
    )


@statsd(namespace="dao")
@transactional
def update_notification_status_by_reference(reference, status):
    # this is used to update letters and emails
    notification = Notification.query.filter(Notification.reference == reference).first()

    if not notification:
        current_app.logger.error("Notification not found for reference %s (update to %s)", reference, status)
        return None

    if notification.status not in TRANSIENT_STATUSES:
        duplicate_update_warning(notification, status)
        return None

    # don't update status by reference if not at least "sending"
    current_index = TRANSIENT_STATUSES.index(notification.status)
    sending_index = TRANSIENT_STATUSES.index(NOTIFICATION_SENDING)
    if current_index < sending_index:
        return None

    return _update_notification_status(
        notification=notification,
        status=status
    )


@statsd(namespace="dao")
@transactional
def dao_update_notification_by_id(notification_id: str, **kwargs):
    """
    Update the notification by ID, ensure kwargs paramaters are named appropriately according to the notification model.
    :param notification_id: The notification uuid in string form
    :param kwargs: The notification key-value pairs to be updated
      Note: Ensure keys are valid according to notification model
    :return: Notification or None
    """
    kwargs['updated_at'] = datetime.utcnow()
    status = kwargs.get('status')

    if notification_id and status is not None:
        update_statement = _get_notification_status_update_statement(
            notification_id=notification_id,
            incoming_status=status,
            **kwargs
        )
    elif notification_id:
        update_statement = (
            update(Notification)
            .where(Notification.id == notification_id)
            .values(kwargs)
        )
    else:
        current_app.logger.error('ERROR: Attempting to update without providing required notification ID field.')
        return None

    try:
        db.session.execute(update_statement)
        db.session.commit()
    except NoResultFound as e:
        current_app.logger.warning(
            'No notification found with id %s when attempting to update - exception %s', notification_id, e
        )
        return None
    except ArgumentError as e:
        current_app.logger.warning(
            'Cannot update notification %s - exception: %s', notification_id, e
        )
        return None
    except Exception as e:
        current_app.logger.error(
            'Unexpected exception thrown attempting to update notification %s, given parameters for updating '
            'notification may be incorrect - Exception: %s', notification_id, e
        )
        return None

    return db.session.get(Notification, notification_id)


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
        page_size = current_app.config['PAGE_SIZE']
    query = Notification.query.filter_by(service_id=service_id, job_id=job_id)
    query = _filter_query(query, filter_dict)
    return query.order_by(asc(Notification.job_row_number)).paginate(
        page=page,
        per_page=page_size
    )


@statsd(namespace="dao")
def get_notification_with_personalisation(service_id, notification_id, key_type):
    filter_dict = {'service_id': service_id, 'id': notification_id}
    if key_type:
        filter_dict['key_type'] = key_type

    return Notification.query.filter_by(**filter_dict).options(joinedload('template')).one()


@statsd(namespace="dao")
def get_notification_by_id(notification_id, service_id=None, _raise=False):
    filters = [Notification.id == notification_id]

    if service_id:
        filters.append(Notification.service_id == service_id)

    query = Notification.query.filter(*filters)

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
        include_one_off=True
):
    if page_size is None:
        page_size = current_app.config['PAGE_SIZE']

    filters = [Notification.service_id == service_id]

    if limit_days is not None:
        filters.append(Notification.created_at >= midnight_n_days_ago(limit_days))

    if older_than is not None:
        older_than_created_at = db.session.query(
            Notification.created_at).filter(Notification.id == older_than).as_scalar()
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
        query = query.options(
            joinedload('template')
        )

    return query.order_by(desc(Notification.created_at)).paginate(
        page=page,
        per_page=page_size,
        count=count_pages
    )


def _filter_query(query, filter_dict=None):
    if filter_dict is None:
        return query

    multidict = MultiDict(filter_dict)

    # filter by status
    statuses = multidict.getlist('status')
    if statuses:
        statuses = Notification.substitute_status(statuses)
        query = query.filter(Notification.status.in_(statuses))

    # filter by template
    template_types = multidict.getlist('template_type')
    if template_types:
        query = query.filter(Notification.notification_type.in_(template_types))

    return query


@statsd(namespace="dao")
def delete_notifications_older_than_retention_by_type(notification_type, qry_limit=10000):
    """
    TODO - This seems unnecessarily complicated.  It can probably be reduced to a single "delete"
    query with a "join" and a compound "where" clause.  See #1102.
    """

    current_app.logger.info(
        'Deleting %s notifications for services with flexible data retention', notification_type
    )

    flexible_data_retention = ServiceDataRetention.query.filter(
        ServiceDataRetention.notification_type == notification_type
    ).all()

    deleted = 0

    for f in flexible_data_retention:
        days_of_retention = get_local_timezone_midnight_in_utc(
            convert_utc_to_local_timezone(datetime.utcnow()).date()) - timedelta(days=f.days_of_retention)

        if notification_type == LETTER_TYPE:
            _delete_letters_from_s3(
                notification_type, f.service_id, days_of_retention, qry_limit
            )

        insert_update_notification_history(notification_type, days_of_retention, f.service_id)

        current_app.logger.info(
            "Deleting %s notifications for service id: %s", notification_type, f.service_id
        )
        deleted += _delete_notifications(notification_type, days_of_retention, f.service_id, qry_limit)

    current_app.logger.info(
        'Deleting %s notifications for services without flexible data retention', notification_type
    )

    seven_days_ago = get_local_timezone_midnight_in_utc(
        convert_utc_to_local_timezone(datetime.utcnow()).date()) - timedelta(days=7)
    services_with_data_retention = [x.service_id for x in flexible_data_retention]
    service_ids_to_purge = db.session.query(Service.id).filter(Service.id.notin_(services_with_data_retention)).all()

    for service_id in service_ids_to_purge:
        if notification_type == LETTER_TYPE:
            _delete_letters_from_s3(
                notification_type, service_id, seven_days_ago, qry_limit
            )
        insert_update_notification_history(notification_type, seven_days_ago, service_id)
        deleted += _delete_notifications(notification_type, seven_days_ago, service_id, qry_limit)

    current_app.logger.info('Finished deleting %s notifications', notification_type)

    return deleted


def _delete_notifications(notification_type, date_to_delete_from, service_id, query_limit):
    if isinstance(service_id, Row):
        service_id = str(service_id[0])

    subquery = db.session.query(
        Notification.id
    ).join(NotificationHistory, NotificationHistory.id == Notification.id).filter(
        Notification.notification_type == notification_type,
        Notification.service_id == service_id,
        Notification.created_at < date_to_delete_from,
    ).limit(query_limit).subquery()

    deleted = _delete_for_query(subquery)

    subquery_for_test_keys = db.session.query(
        Notification.id
    ).filter(
        Notification.notification_type == notification_type,
        Notification.service_id == service_id,
        Notification.created_at < date_to_delete_from,
        Notification.key_type == KEY_TYPE_TEST
    ).limit(query_limit).subquery()

    deleted += _delete_for_query(subquery_for_test_keys)

    return deleted


def _delete_for_query(subquery):
    number_deleted = db.session.query(Notification).filter(
        Notification.id.in_(subquery)).delete(synchronize_session='fetch')
    deleted = number_deleted
    db.session.commit()
    while number_deleted > 0:
        number_deleted = db.session.query(Notification).filter(
            Notification.id.in_(subquery)).delete(synchronize_session='fetch')
        deleted += number_deleted
        db.session.commit()
    return deleted


def insert_update_notification_history(notification_type, date_to_delete_from, service_id):
    if isinstance(service_id, Row):
        service_id = str(service_id[0])

    notifications = select(*[text(x.name) for x in NotificationHistory.__table__.c]).where(
        Notification.notification_type == notification_type,
        Notification.service_id == service_id,
        Notification.created_at < date_to_delete_from,
        Notification.key_type != KEY_TYPE_TEST
    )

    stmt = insert(NotificationHistory).from_select(
        NotificationHistory.__table__.c,
        notifications
    )

    stmt = stmt.on_conflict_do_update(
        constraint="notification_history_pkey",
        set_={"notification_status": stmt.excluded.status,
              "reference": stmt.excluded.reference,
              "billable_units": stmt.excluded.billable_units,
              "billing_code": stmt.excluded.billing_code,
              "updated_at": stmt.excluded.updated_at,
              "sent_at": stmt.excluded.sent_at,
              "sent_by": stmt.excluded.sent_by
              }
    )

    db.session.connection().execute(stmt)
    db.session.commit()


def _delete_letters_from_s3(
    notification_type, service_id, date_to_delete_from, query_limit
):
    if isinstance(service_id, Row):
        service_id = str(service_id[0])

    letters_to_delete_from_s3 = db.session.query(
        Notification
    ).filter(
        Notification.notification_type == notification_type,
        Notification.created_at < date_to_delete_from,
        Notification.service_id == service_id
    ).limit(query_limit).all()
    for letter in letters_to_delete_from_s3:
        bucket_name = current_app.config['LETTERS_PDF_BUCKET_NAME']
        if letter.sent_at:
            sent_at = str(letter.sent_at.date())
            prefix = LETTERS_PDF_FILE_LOCATION_STRUCTURE.format(
                folder=sent_at + "/",
                reference=letter.reference,
                duplex="D",
                letter_class="2",
                colour="C",
                crown="C" if letter.service.crown else "N",
                date=''
            ).upper()[:-5]
            s3_objects = get_s3_bucket_objects(bucket_name=bucket_name, subfolder=prefix)
            for s3_object in s3_objects:
                try:
                    remove_s3_object(bucket_name, s3_object['Key'])
                except ClientError:
                    current_app.logger.error(
                        "Could not delete S3 object with filename: %s", s3_object['Key']
                    )


@statsd(namespace="dao")
@transactional
def dao_delete_notification_by_id(notification_id):
    notification = db.session.query(Notification).get(notification_id)
    if notification:
        db.session.delete(notification)


def _timeout_notifications(current_statuses, new_status, timeout_start, updated_at):
    notifications = Notification.query.filter(
        Notification.created_at < timeout_start,
        Notification.status.in_(current_statuses),
        Notification.notification_type != LETTER_TYPE
    ).all()
    Notification.query.filter(
        Notification.created_at < timeout_start,
        Notification.status.in_(current_statuses),
        Notification.notification_type != LETTER_TYPE
    ).update(
        {'status': new_status, 'updated_at': updated_at},
        synchronize_session=False
    )
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
    temporary_failure_notifications = timeout([NOTIFICATION_SENDING, NOTIFICATION_PENDING],
                                              NOTIFICATION_TEMPORARY_FAILURE)

    db.session.commit()

    return technical_failure_notifications, temporary_failure_notifications


def is_delivery_slow_for_provider(
        created_at,
        provider,
        threshold,
        delivery_time,
):
    count = db.session.query(
        case(
            [(
                Notification.status == NOTIFICATION_DELIVERED,
                (Notification.updated_at - Notification.sent_at) >= delivery_time
            )],
            else_=(datetime.utcnow() - Notification.sent_at) >= delivery_time
        ).label("slow"), func.count()

    ).filter(
        Notification.created_at >= created_at,
        Notification.sent_at.isnot(None),
        Notification.status.in_([NOTIFICATION_DELIVERED, NOTIFICATION_PENDING, NOTIFICATION_SENDING]),
        Notification.sent_by == provider,
        Notification.key_type != KEY_TYPE_TEST
    ).group_by("slow").all()

    counts = {c[0]: c[1] for c in count}
    total_notifications = sum(counts.values())
    slow_notifications = counts.get(True, 0)

    if total_notifications:
        current_app.logger.info(
            "Slow delivery notifications count for provider %s: %d out of %d. Ratio %.3f",
            provider, slow_notifications, total_notifications, slow_notifications / total_notifications
        )
        return slow_notifications / total_notifications >= threshold
    else:
        return False


@statsd(namespace="dao")
@transactional
def dao_update_notifications_by_reference(references, update_dict):
    updated_count = Notification.query.filter(
        Notification.reference.in_(references)
    ).update(
        update_dict,
        synchronize_session=False
    )

    updated_history_count = 0
    if updated_count != len(references):
        updated_history_count = NotificationHistory.query.filter(
            NotificationHistory.reference.in_(references)
        ).update(
            update_dict,
            synchronize_session=False
        )

    return updated_count, updated_history_count


@statsd(namespace="dao")
def dao_get_notifications_by_to_field(service_id, search_term, notification_type=None, statuses=None):
    if notification_type is None:
        notification_type = guess_notification_type(search_term)

    if notification_type == SMS_TYPE:
        normalised = try_validate_and_format_phone_number(search_term)

        for character in "() -":
            normalised = normalised.replace(character, '')

        normalised = normalised.lstrip('+0')
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
        Notification.normalised_to.like(f"%{normalised}%"),
        Notification.key_type != KEY_TYPE_TEST,
    ]

    if statuses:
        filters.append(Notification.status.in_(statuses))
    if notification_type:
        filters.append(Notification.notification_type == notification_type)

    return db.session.query(Notification).filter(*filters).order_by(desc(Notification.created_at)).all()


@statsd(namespace="dao")
def dao_get_notification_by_reference(reference):
    return Notification.query.filter(
        Notification.reference == reference
    ).one()


@statsd(namespace="dao")
def dao_get_notification_history_by_reference(reference):
    try:
        # This try except is necessary because in test keys and research mode does not create notification history.
        # Otherwise we could just search for the NotificationHistory object
        return Notification.query.filter(
            Notification.reference == reference
        ).one()
    except NoResultFound:
        return NotificationHistory.query.filter(
            NotificationHistory.reference == reference
        ).one()


@statsd(namespace="dao")
def dao_get_notifications_by_references(references):
    return Notification.query.filter(
        Notification.reference.in_(references)
    ).all()


@statsd(namespace="dao")
def dao_created_scheduled_notification(scheduled_notification):
    db.session.add(scheduled_notification)
    db.session.commit()


@statsd(namespace="dao")
def dao_get_scheduled_notifications():
    notifications = Notification.query.join(
        ScheduledNotification
    ).filter(
        ScheduledNotification.scheduled_for < datetime.utcnow(),
        ScheduledNotification.pending).all()

    return notifications


def set_scheduled_notification_to_processed(notification_id):
    db.session.query(ScheduledNotification).filter(
        ScheduledNotification.notification_id == notification_id
    ).update(
        {'pending': False}
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
    sum_column = functions.coalesce(functions.sum(
        case(
            [
                (under_10_secs, 1)
            ],
            else_=0
        )
    ), 0)

    return db.session.query(
        func.count(Notification.id).label('messages_total'),
        sum_column.label('messages_within_10_secs')
    ).filter(
        Notification.created_at >= start_date,
        Notification.created_at < end_date,
        Notification.api_key_id.isnot(None),
        Notification.key_type != KEY_TYPE_TEST,
        Notification.notification_type != LETTER_TYPE
    ).one()


@statsd(namespace="dao")
def dao_get_last_notification_added_for_job_id(job_id):
    last_notification_added = Notification.query.filter(
        Notification.job_id == job_id
    ).order_by(
        Notification.job_row_number.desc()
    ).first()

    return last_notification_added


def notifications_not_yet_sent(should_be_sending_after_seconds, notification_type):
    older_than_date = datetime.utcnow() - timedelta(seconds=should_be_sending_after_seconds)

    notifications = Notification.query.filter(
        Notification.created_at <= older_than_date,
        Notification.notification_type == notification_type,
        Notification.status == NOTIFICATION_CREATED,
        Notification.to is not None
    ).all()
    return notifications


def dao_old_letters_with_created_status():
    yesterday_bst = convert_utc_to_local_timezone(datetime.utcnow()) - timedelta(days=1)
    last_processing_deadline = yesterday_bst.replace(hour=17, minute=30, second=0, microsecond=0)

    notifications = Notification.query.filter(
        Notification.updated_at < convert_local_timezone_to_utc(last_processing_deadline),
        Notification.notification_type == LETTER_TYPE,
        Notification.status == NOTIFICATION_CREATED
    ).order_by(
        Notification.updated_at
    ).all()
    return notifications


def dao_precompiled_letters_still_pending_virus_check():
    ninety_minutes_ago = datetime.utcnow() - timedelta(seconds=5400)

    notifications = Notification.query.filter(
        Notification.created_at < ninety_minutes_ago,
        Notification.status == NOTIFICATION_PENDING_VIRUS_CHECK
    ).order_by(
        Notification.created_at
    ).all()
    return notifications


def guess_notification_type(search_term):
    if set(search_term) & set(string.ascii_letters + '@'):
        return EMAIL_TYPE
    else:
        return SMS_TYPE


def duplicate_update_warning(notification, status):
    # This is a log, so this is not SQL injection
    time_diff = datetime.utcnow() - (notification.updated_at or notification.created_at)

    current_app.logger.info(
        'Duplicate callback received. Notification id %s received a status update to '
        '%s %s after being set to %s. %s sent by %s',
        notification.id, status, time_diff, notification.status, notification.notification_type, notification.sent_by
    )
