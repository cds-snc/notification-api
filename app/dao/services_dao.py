import uuid
from datetime import date, datetime, timedelta

from cachetools import TTLCache, cached
from flask import current_app
from notifications_utils.statsd_decorators import statsd
from notifications_utils.timezones import convert_utc_to_local_timezone
from sqlalchemy import delete, func, select
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound
from sqlalchemy.sql.expression import and_, asc, case

from app import db
from app.dao.dao_utils import VersionOptions, get_reader_session, transactional, version_class
from app.dao.organisation_dao import dao_get_organisation_by_email_address
from app.dao.service_sms_sender_dao import insert_service_sms_sender
from app.dao.service_user_dao import dao_get_service_user
from app.dao.template_folder_dao import dao_get_valid_template_folders_by_id
from app.model import User
from app.models import (
    EMAIL_TYPE,
    INTERNATIONAL_SMS_TYPE,
    KEY_TYPE_TEST,
    SMS_TYPE,
    AnnualBilling,
    ApiKey,
    FactBilling,
    InboundNumber,
    InvitedUser,
    Job,
    Notification,
    NotificationHistory,
    Organisation,
    Permission,
    Service,
    ServicePermission,
    ServiceSmsSender,
    Template,
    TemplateHistory,
    TemplateRedacted,
    VerifyCode,
)
from app.service.service_data import ServiceData, ServiceDataException
from app.utils import escape_special_characters, get_local_timezone_midnight_in_utc, midnight_n_days_ago

# Do not confuse this with "default_service_permissions" in app/dao/permissions_dao.py.
DEFAULT_SERVICE_PERMISSIONS = [
    SMS_TYPE,
    EMAIL_TYPE,
    INTERNATIONAL_SMS_TYPE,
]


def dao_fetch_all_services(only_active=False):
    stmt = select(Service).order_by(asc(Service.created_at)).options(joinedload('users'))

    if only_active:
        stmt = stmt.where(Service.active)

    return db.session.scalars(stmt).unique().all()


def get_services_by_partial_name(service_name):
    service_name = escape_special_characters(service_name)
    stmt = select(Service).where(Service.name.ilike('%{}%'.format(service_name)))
    return db.session.scalars(stmt).all()


def dao_count_live_services():
    stmt = (
        select(func.count())
        .select_from(Service)
        .where(Service.active.is_(True), Service.restricted.is_(False), Service.count_as_live.is_(True))
    )
    return db.session.scalar(stmt)


def dao_fetch_live_services_data():
    # most recent annual billing
    most_recent_annual_stmt = (
        select(AnnualBilling.service_id, func.max(AnnualBilling.financial_year_start).label('year'))
        .group_by(AnnualBilling.service_id)
        .subquery()
    )
    # this year ft billing
    this_year_ft_stmt = select(FactBilling).subquery()
    stmt = (
        select(
            Service.id.label('service_id'),
            Service.name.label('service_name'),
            Organisation.name.label('organisation_name'),
            Organisation.organisation_type.label('organisation_type'),
            Service.consent_to_research.label('consent_to_research'),
            User.name.label('contact_name'),
            User.email_address.label('contact_email'),
            User.mobile_number.label('contact_mobile'),
            Service.go_live_at.label('live_date'),
            Service.volume_sms.label('sms_volume_intent'),
            Service.volume_email.label('email_volume_intent'),
            Service.volume_letter.label('letter_volume_intent'),
            case(
                [(this_year_ft_stmt.c.notification_type == 'email', func.sum(this_year_ft_stmt.c.notifications_sent))],
                else_=0,
            ).label('email_totals'),
            case(
                [(this_year_ft_stmt.c.notification_type == 'sms', func.sum(this_year_ft_stmt.c.notifications_sent))],
                else_=0,
            ).label('sms_totals'),
            case(
                [(this_year_ft_stmt.c.notification_type == 'letter', func.sum(this_year_ft_stmt.c.notifications_sent))],
                else_=0,
            ).label('letter_totals'),
            AnnualBilling.free_sms_fragment_limit,
        )
        .join(Service.annual_billing)
        .join(
            most_recent_annual_stmt,
            and_(
                Service.id == most_recent_annual_stmt.c.service_id,
                AnnualBilling.financial_year_start == most_recent_annual_stmt.c.year,
            ),
        )
        .outerjoin(Service.organisation)
        .outerjoin(this_year_ft_stmt, Service.id == this_year_ft_stmt.c.service_id)
        .outerjoin(User, Service.go_live_user_id == User.id)
        .where(
            Service.count_as_live.is_(True),
            Service.active.is_(True),
            Service.restricted.is_(False),
        )
        .group_by(
            Service.id,
            Organisation.name,
            Organisation.organisation_type,
            Service.name,
            Service.consent_to_research,
            Service.count_as_live,
            Service.go_live_user_id,
            User.name,
            User.email_address,
            User.mobile_number,
            Service.go_live_at,
            Service.volume_sms,
            Service.volume_email,
            Service.volume_letter,
            this_year_ft_stmt.c.notification_type,
            AnnualBilling.free_sms_fragment_limit,
        )
        .order_by(asc(Service.go_live_at))
    )
    data = db.session.execute(stmt).all()

    results = []
    for row in data:
        existing_service = next((x for x in results if x['service_id'] == row.service_id), None)

        if existing_service is not None:
            existing_service['email_totals'] += row.email_totals
            existing_service['sms_totals'] += row.sms_totals
            existing_service['letter_totals'] += row.letter_totals
        else:
            results.append(row._asdict())

    return results


def dao_fetch_service_by_id(
    service_id,
    only_active=False,
):
    stmt = select(Service).where(Service.id == service_id).options(joinedload('users'))

    if only_active:
        stmt = stmt.where(Service.active)

    return db.session.scalars(stmt).unique().one()


def dao_fetch_service_by_inbound_number(number):
    stmt = select(InboundNumber).where(InboundNumber.number == number, InboundNumber.active)
    inbound_number = db.session.execute(stmt).scalar_one_or_none()

    if not inbound_number:
        return None

    stmt = select(Service).where(Service.id == inbound_number.service_id)
    return db.session.execute(stmt).scalar_one_or_none()


@cached(cache=TTLCache(maxsize=1024, ttl=600))
def dao_fetch_service_by_id_with_api_keys(
    service_id,
    only_active=False,
):
    with get_reader_session() as session:
        # Constructing the query
        stmt = select(Service).where(Service.id == service_id).options(joinedload('api_keys'))

        if only_active:
            stmt = stmt.where(Service.active)

        try:
            # Execute the query and fetch one record
            result = session.scalars(stmt).unique().one()
            # Extract needed properties and return object for caching
            return ServiceData(result)
        except (ServiceDataException, NoResultFound, MultipleResultsFound) as err:
            # we handle this failure in the parent
            current_app.logger.error('Could not find unique service with ID %s', service_id)
            raise NoResultFound from err


def dao_fetch_all_services_by_user(
    user_id,
    only_active=False,
):
    stmt = (
        select(Service)
        .where(Service.users.any(id=user_id))
        .order_by(asc(Service.created_at))
        .options(joinedload('users'))
    )

    if only_active:
        stmt = stmt.where(Service.active)

    return db.session.scalars(stmt).unique().all()


@transactional
@version_class(
    VersionOptions(ApiKey, must_write_history=False),
    VersionOptions(Service),
    VersionOptions(Template, history_class=TemplateHistory, must_write_history=False),
)
def dao_archive_service(service_id):
    # TODO - this needs a unit test

    # have to eager load templates and api keys so that we don't flush when we loop through them
    # to ensure that db.session still contains the models when it comes to creating history objects
    stmt = (
        select(Service)
        .options(
            joinedload(Service.templates),
            joinedload(Service.templates).joinedload(Template.template_redacted),
            joinedload(Service.api_keys),
        )
        .where(Service.id == service_id)
    )
    service = db.session.scalars(stmt).unique().one()

    time = datetime.utcnow().strftime('%Y-%m-%d_%H:%M:%S')
    service.active = False
    service.name = '_archived_' + time + '_' + service.name
    service.email_from = '_archived_' + time + '_' + service.email_from

    for template in service.templates:
        if not template.archived:
            template.archived = True

    for api_key in service.api_keys:
        if not api_key.expiry_date:
            api_key.expiry_date = datetime.utcnow()


@transactional
@version_class(Service)
def dao_create_service(
    service,
    user,
    service_id=None,
    service_permissions=None,
):
    # the default property does not appear to work when there is a difference between the sqlalchemy schema and the
    # db schema (ie: during a migration), so we have to set sms_sender manually here. After the GOVUK sms_sender
    # migration is completed, this code should be able to be removed.

    if not user:
        raise ValueError("Can't create a service without a user")

    if service_permissions is None:
        service_permissions = DEFAULT_SERVICE_PERMISSIONS

    organisation = dao_get_organisation_by_email_address(user.email_address)

    from app.dao.permissions_dao import permission_dao

    service.users.append(user)
    permission_dao.add_default_service_permissions_for_user(user, service)
    service.id = service_id or uuid.uuid4()  # must be set now so version history model can use same id
    service.active = True
    service.research_mode = False

    for permission in service_permissions:
        service_permission = ServicePermission(service_id=service.id, permission=permission)
        service.permissions.append(service_permission)

    # do we just add the default - or will we get a value from FE?
    insert_service_sms_sender(service, current_app.config['FROM_NUMBER'])

    if organisation:
        service.organisation_id = organisation.id
        service.organisation_type = organisation.organisation_type
        if organisation.email_branding:
            service.email_branding = organisation.email_branding

        service.crown = organisation.crown

    service.count_as_live = not user.platform_admin

    db.session.add(service)


@transactional
@version_class(Service)
def dao_update_service(service):
    db.session.add(service)


def dao_add_user_to_service(
    service,
    user,
    permissions=None,
    folder_permissions=None,
):
    permissions = permissions or []
    folder_permissions = folder_permissions or []

    try:
        from app.dao.permissions_dao import permission_dao

        service.users.append(user)
        permission_dao.set_user_service_permission(user, service, permissions, _commit=False)
        db.session.add(service)

        service_user = dao_get_service_user(user.id, service.id)
        valid_template_folders = dao_get_valid_template_folders_by_id(folder_permissions)
        service_user.folders = valid_template_folders
        db.session.add(service_user)

    except:
        db.session.rollback()
        raise
    else:
        db.session.commit()


def dao_remove_user_from_service(
    service,
    user,
):
    try:
        from app.dao.permissions_dao import permission_dao

        permission_dao.remove_user_service_permissions(user, service)

        service_user = dao_get_service_user(user.id, service.id)
        db.session.delete(service_user)
    except:
        db.session.rollback()
        raise
    else:
        db.session.commit()


def delete_service_and_all_associated_db_objects(service):
    def _delete_commit(stmt):
        db.session.execute(stmt, execution_options={'synchronize_session': False})
        db.session.commit()

    template_ids_subquery = select(Template.id).where(Template.service == service).subquery()
    _delete_commit(delete(TemplateRedacted).where(TemplateRedacted.template_id.in_(template_ids_subquery)))
    _delete_commit(delete(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id))
    _delete_commit(delete(InvitedUser).where(InvitedUser.service_id == service.id))
    _delete_commit(delete(Permission).where(Permission.service_id == service.id))
    _delete_commit(delete(NotificationHistory).where(NotificationHistory.service_id == service.id))
    _delete_commit(delete(Notification).where(Notification.service_id == service.id))
    _delete_commit(delete(Job).where(Job.service_id == service.id))
    _delete_commit(delete(Template).where(Template.service_id == service.id))
    _delete_commit(delete(TemplateHistory).where(TemplateHistory.service_id == service.id))
    _delete_commit(delete(ServicePermission).where(ServicePermission.service_id == service.id))
    _delete_commit(delete(ApiKey).where(ApiKey.service_id == service.id))
    _delete_commit(delete(ApiKey.get_history_model()).where(ApiKey.get_history_model().service_id == service.id))
    _delete_commit(delete(AnnualBilling).where(AnnualBilling.service_id == service.id))

    user_ids = [x.id for x in service.users]
    users = [x for x in service.users]

    verify_codes_stmt = select(VerifyCode).join(User).where(User.id.in_(user_ids))
    for verify_code in db.session.scalars(verify_codes_stmt).all():
        db.session.delete(verify_code)
    db.session.commit()

    for user in users:
        service.users.remove(user)

    _delete_commit(delete(Service.get_history_model()).where(Service.get_history_model().id == service.id))
    db.session.delete(service)
    db.session.commit()

    for user in users:
        db.session.delete(user)
    db.session.commit()


@statsd(namespace='dao')
def dao_fetch_stats_for_service(
    service_id,
    limit_days,
):
    # We always want between seven and eight days
    start_date = midnight_n_days_ago(limit_days)
    stmt = _stats_for_service_query(service_id).where(Notification.created_at >= start_date)
    return db.session.execute(stmt).all()


@statsd(namespace='dao')
def dao_fetch_todays_stats_for_service(service_id):
    stmt = _stats_for_service_query(service_id).where(func.date(Notification.created_at) == date.today())
    return db.session.execute(stmt).all()


def fetch_todays_total_message_count(service_id):
    stmt = select(func.count(Notification.id).label('count')).where(
        Notification.service_id == service_id,
        Notification.key_type != KEY_TYPE_TEST,
        func.date(Notification.created_at) == date.today(),
    )
    return db.session.scalar(stmt)


def _stats_for_service_query(service_id):
    return (
        select(Notification.notification_type, Notification.status, func.count(Notification.id).label('count'))
        .where(Notification.service_id == service_id, Notification.key_type != KEY_TYPE_TEST)
        .group_by(
            Notification.notification_type,
            Notification.status,
        )
    )


@statsd(namespace='dao')
def dao_fetch_todays_stats_for_all_services(
    include_from_test_key=True,
    only_active=True,
):
    today = convert_utc_to_local_timezone(datetime.utcnow())
    start_date = get_local_timezone_midnight_in_utc(today)
    end_date = get_local_timezone_midnight_in_utc(today + timedelta(days=1))

    subquery_stmt = (
        select(
            Notification.notification_type,
            Notification.status,
            Notification.service_id,
            func.count(Notification.id).label('count'),
        )
        .where(Notification.created_at >= start_date, Notification.created_at < end_date)
        .group_by(Notification.notification_type, Notification.status, Notification.service_id)
    )

    if not include_from_test_key:
        subquery_stmt = subquery_stmt.where(Notification.key_type != KEY_TYPE_TEST)

    subquery = subquery_stmt.subquery()
    stmt = (
        select(
            Service.id.label('service_id'),
            Service.name,
            Service.restricted,
            Service.research_mode,
            Service.active,
            Service.created_at,
            subquery.c.notification_type,
            subquery.c.status,
            subquery.c.count,
        )
        .outerjoin(subquery, subquery.c.service_id == Service.id)
        .order_by(Service.id)
    )

    if only_active:
        stmt = stmt.where(Service.active)

    return db.session.execute(stmt).all()


@transactional
@version_class(
    VersionOptions(ApiKey, must_write_history=False),
    VersionOptions(Service),
)
def dao_suspend_service(service_id):
    # have to eager load api keys so that we don't flush when we loop through them
    # to ensure that db.session still contains the models when it comes to creating history objects
    stmt = select(Service).options(joinedload(Service.api_keys)).where(Service.id == service_id)
    service = db.session.scalars(stmt).unique().one()

    for api_key in service.api_keys:
        if not api_key.expiry_date:
            api_key.expiry_date = datetime.utcnow()

    service.active = False


@transactional
@version_class(Service)
def dao_resume_service(service_id):
    service = db.session.get(Service, service_id)
    service.active = True


def dao_fetch_active_users_for_service(service_id):
    stmt = select(User).where(User.services.any(id=service_id), User.state == 'active')
    return db.session.scalars(stmt).all()


def dao_services_by_partial_smtp_name(smtp_name):
    smtp_name = escape_special_characters(smtp_name)
    stmt = select(Service).where(Service.smtp_user.ilike(f'%{smtp_name}%'))
    return db.session.scalars(stmt).one()
