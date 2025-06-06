import json
import uuid
from datetime import date, datetime, timedelta

import pytz
from flask import current_app
from notifications_utils.clients.redis import service_cache_key
from notifications_utils.statsd_decorators import statsd
from notifications_utils.timezones import convert_utc_to_local_timezone
from sqlalchemy.orm import joinedload
from sqlalchemy.sql.expression import and_, asc, case, func

from app import db, redis_store
from app.dao.dao_utils import VersionOptions, transactional, version_class
from app.dao.date_util import get_current_financial_year, get_midnight
from app.dao.email_branding_dao import dao_get_email_branding_by_name
from app.dao.letter_branding_dao import dao_get_letter_branding_by_name
from app.dao.organisation_dao import dao_get_organisation_by_email_address
from app.dao.permissions_dao import permission_dao
from app.dao.service_sms_sender_dao import insert_service_sms_sender
from app.dao.service_user_dao import dao_get_service_user
from app.dao.template_folder_dao import dao_get_valid_template_folders_by_id
from app.models import (
    CROWN_ORGANISATION_TYPES,
    EMAIL_TYPE,
    INTERNATIONAL_SMS_TYPE,
    JOB_STATUS_SCHEDULED,
    KEY_TYPE_TEST,
    NHS_ORGANISATION_TYPES,
    NON_CROWN_ORGANISATION_TYPES,
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
    TemplateCategory,
    TemplateHistory,
    TemplateRedacted,
    User,
    VerifyCode,
)
from app.service.utils import add_pt_data_retention, get_organisation_by_id
from app.utils import (
    email_address_is_nhs,
    escape_special_characters,
    get_local_timezone_midnight_in_utc,
    midnight_n_days_ago,
)

DEFAULT_SERVICE_PERMISSIONS = [
    SMS_TYPE,
    EMAIL_TYPE,
    INTERNATIONAL_SMS_TYPE,
]


def dao_fetch_all_services(only_active=False):
    query = Service.query.order_by(asc(Service.created_at)).options(joinedload("users"))

    if only_active:
        query = query.filter(Service.active)

    return query.all()


def get_services_by_partial_name(service_name):
    service_name = escape_special_characters(service_name)
    return Service.query.filter(Service.name.ilike("%{}%".format(service_name))).all()


def dao_count_live_services():
    return Service.query.filter_by(
        active=True,
        restricted=False,
        count_as_live=True,
    ).count()


def dao_fetch_live_services_data(filter_heartbeats=None):
    year_start_date, year_end_date = get_current_financial_year()

    most_recent_annual_billing = (
        db.session.query(
            AnnualBilling.service_id,
            func.max(AnnualBilling.financial_year_start).label("year"),
        )
        .group_by(AnnualBilling.service_id)
        .subquery()
    )

    this_year_ft_billing = FactBilling.query.subquery()

    data = (
        db.session.query(
            Service.id.label("service_id"),
            Service.name.label("service_name"),
            Organisation.name.label("organisation_name"),
            Organisation.organisation_type.label("organisation_type"),
            Service.consent_to_research.label("consent_to_research"),
            User.name.label("contact_name"),
            User.email_address.label("contact_email"),
            User.mobile_number.label("contact_mobile"),
            Service.go_live_at.label("live_date"),
            Service.volume_sms.label("sms_volume_intent"),
            Service.volume_email.label("email_volume_intent"),
            Service.volume_letter.label("letter_volume_intent"),
            case(
                [
                    (
                        this_year_ft_billing.c.notification_type == "email",
                        func.sum(this_year_ft_billing.c.notifications_sent),
                    )
                ],
                else_=0,
            ).label("email_totals"),
            case(
                [
                    (
                        this_year_ft_billing.c.notification_type == "sms",
                        func.sum(this_year_ft_billing.c.notifications_sent),
                    )
                ],
                else_=0,
            ).label("sms_totals"),
            case(
                [
                    (
                        this_year_ft_billing.c.notification_type == "letter",
                        func.sum(this_year_ft_billing.c.notifications_sent),
                    )
                ],
                else_=0,
            ).label("letter_totals"),
            AnnualBilling.free_sms_fragment_limit,
        )
        .join(Service.annual_billing)
        .join(
            most_recent_annual_billing,
            and_(
                Service.id == most_recent_annual_billing.c.service_id,
                AnnualBilling.financial_year_start == most_recent_annual_billing.c.year,
            ),
        )
        .outerjoin(Service.organisation)
        .outerjoin(this_year_ft_billing, Service.id == this_year_ft_billing.c.service_id)
        .outerjoin(User, Service.go_live_user_id == User.id)
        .filter(
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
            this_year_ft_billing.c.notification_type,
            AnnualBilling.free_sms_fragment_limit,
        )
        .order_by(asc(Service.go_live_at))
    )

    if filter_heartbeats:
        data = data.filter(Service.id != current_app.config["NOTIFY_SERVICE_ID"])
    data = data.all()
    results = []
    for row in data:
        existing_service = next((x for x in results if x["service_id"] == row.service_id), None)

        if existing_service is not None:
            existing_service["email_totals"] += row.email_totals
            existing_service["sms_totals"] += row.sms_totals
            existing_service["letter_totals"] += row.letter_totals
        else:
            results.append(row._asdict())
    return results


def dao_fetch_service_by_id(service_id, only_active=False, use_cache=False) -> Service:
    if use_cache:
        service_cache = redis_store.get(service_cache_key(service_id))
        if service_cache:
            service_cache_decoded = json.loads(service_cache.decode("utf-8"))["data"]
            return Service.from_json(service_cache_decoded)

    query = Service.query.filter_by(id=service_id).options(joinedload("users"))
    if only_active:
        query = query.filter(Service.active)
    return query.one()


def dao_fetch_service_by_inbound_number(number):
    inbound_number = InboundNumber.query.filter(InboundNumber.number == number, InboundNumber.active).first()

    if not inbound_number:
        return None

    return Service.query.filter(Service.id == inbound_number.service_id).first()


def dao_fetch_service_by_id_with_api_keys(service_id, only_active=False):
    query = db.on_reader().query(Service).filter_by(id=service_id).options(joinedload("api_keys"))

    if only_active:
        query = query.filter(Service.active)

    return query.one()


def dao_fetch_all_services_by_user(user_id, only_active=False):
    query = Service.query.filter(Service.users.any(id=user_id)).order_by(asc(Service.created_at)).options(joinedload("users"))

    if only_active:
        query = query.filter(Service.active)

    return query.all()


@transactional
@version_class(
    VersionOptions(ApiKey, must_write_history=False),
    VersionOptions(Service),
    VersionOptions(Template, history_class=TemplateHistory, must_write_history=False),
)
def dao_archive_service(service_id):
    # have to eager load templates and api keys so that we don't flush when we loop through them
    # to ensure that db.session still contains the models when it comes to creating history objects
    service = (
        Service.query.options(
            joinedload("templates"),
            joinedload("templates.template_redacted"),
            joinedload("api_keys"),
        )
        .filter(Service.id == service_id)
        .one()
    )

    time = datetime.utcnow().strftime("%Y-%m-%d_%H:%M:%S")
    service.active = False
    service.name = "_archived_" + time + "_" + service.name
    service.email_from = "_archived_" + time + "_" + service.email_from

    for template in service.templates:
        if not template.archived:
            template.archived = True

    for api_key in service.api_keys:
        if not api_key.expiry_date:
            api_key.expiry_date = datetime.utcnow()


def dao_fetch_service_by_id_and_user(service_id, user_id):
    return Service.query.filter(Service.users.any(id=user_id), Service.id == service_id).options(joinedload("users")).one()


@transactional
@version_class(Service)
def dao_create_service(
    service,
    user,
    service_id=None,
    service_permissions=None,
    organisation_id=None,
):
    # the default property does not appear to work when there is a difference between the sqlalchemy schema and the
    # db schema (ie: during a migration), so we have to set sms_sender manually here. After the GOVUK sms_sender
    # migration is completed, this code should be able to be removed.

    if not user:
        raise ValueError("Can't create a service without a user")

    if service_permissions is None:
        service_permissions = DEFAULT_SERVICE_PERMISSIONS

    if organisation_id:
        organisation = get_organisation_by_id(organisation_id)
    else:
        organisation = dao_get_organisation_by_email_address(user.email_address)

    service.users.append(user)
    permission_dao.add_default_service_permissions_for_user(user, service)
    service.id = service_id or uuid.uuid4()  # must be set now so version history model can use same id
    service.active = True
    service.research_mode = False

    for permission in service_permissions:
        service_permission = ServicePermission(service_id=service.id, permission=permission)
        service.permissions.append(service_permission)

    # do we just add the default - or will we get a value from FE?
    insert_service_sms_sender(service, current_app.config["FROM_NUMBER"])

    if organisation:
        service.organisation_id = organisation.id
        service.organisation_type = organisation.organisation_type

        if organisation.letter_branding and not service.letter_branding:
            service.letter_branding = organisation.letter_branding

        if organisation.organisation_type == "province_or_territory":
            add_pt_data_retention(service.id)

    elif service.organisation_type in NHS_ORGANISATION_TYPES or email_address_is_nhs(user.email_address):
        service.email_branding = dao_get_email_branding_by_name("NHS")
        service.letter_branding = dao_get_letter_branding_by_name("NHS")
    if organisation:
        service.crown = organisation.crown
    elif service.organisation_type in CROWN_ORGANISATION_TYPES:
        service.crown = True
    elif service.organisation_type in NON_CROWN_ORGANISATION_TYPES:
        service.crown = False
    service.count_as_live = not user.platform_admin

    db.session.add(service)


@transactional
@version_class(Service)
def dao_update_service(service):
    db.session.add(service)


def dao_add_user_to_service(service, user, permissions=None, folder_permissions=None):
    permissions = permissions or []
    folder_permissions = folder_permissions or []

    try:
        service.users.append(user)
        permission_dao.set_user_service_permission(user, service, permissions, _commit=False)
        db.session.add(service)

        service_user = dao_get_service_user(user.id, service.id)
        valid_template_folders = dao_get_valid_template_folders_by_id(folder_permissions)
        service_user.folders = valid_template_folders
        db.session.add(service_user)

    except Exception as e:
        db.session.rollback()
        raise e
    else:
        db.session.commit()


def dao_remove_user_from_service(service, user):
    try:
        from app.dao.permissions_dao import permission_dao

        permission_dao.remove_user_service_permissions(user, service)

        service_user = dao_get_service_user(user.id, service.id)
        db.session.delete(service_user)
    except Exception as e:
        db.session.rollback()
        raise e
    else:
        db.session.commit()


def delete_service_and_all_associated_db_objects(service):
    def _delete_commit(query):
        query.delete(synchronize_session=False)
        db.session.commit()

    subq = db.session.query(Template.id).filter_by(service=service).subquery()
    _delete_commit(TemplateRedacted.query.filter(TemplateRedacted.template_id.in_(subq)))

    _delete_commit(ServiceSmsSender.query.filter_by(service=service))
    _delete_commit(InvitedUser.query.filter_by(service=service))
    _delete_commit(Permission.query.filter_by(service=service))
    _delete_commit(NotificationHistory.query.filter_by(service=service))
    _delete_commit(Notification.query.filter_by(service=service))
    _delete_commit(Job.query.filter_by(service=service))
    _delete_commit(Template.query.filter_by(service=service))
    _delete_commit(TemplateHistory.query.filter_by(service_id=service.id))
    _delete_commit(ServicePermission.query.filter_by(service_id=service.id))
    _delete_commit(ApiKey.query.filter_by(service=service))
    _delete_commit(ApiKey.get_history_model().query.filter_by(service_id=service.id))
    _delete_commit(AnnualBilling.query.filter_by(service_id=service.id))

    verify_codes = VerifyCode.query.join(User).filter(User.id.in_([x.id for x in service.users]))
    list(map(db.session.delete, verify_codes))
    db.session.commit()
    users = [x for x in service.users]
    for user in users:
        _delete_commit(TemplateCategory.query.filter_by(created_by_id=user.id))
    map(service.users.remove, users)
    [service.users.remove(x) for x in users]
    _delete_commit(Service.get_history_model().query.filter_by(id=service.id))
    db.session.delete(service)
    db.session.commit()
    list(map(db.session.delete, users))
    db.session.commit()


@statsd(namespace="dao")
def dao_fetch_stats_for_service(service_id, limit_days):
    # We always want between seven and eight days
    start_date = midnight_n_days_ago(limit_days)
    return _stats_for_service_query(service_id).filter(Notification.created_at >= start_date).all()


@statsd(namespace="dao")
def dao_fetch_todays_stats_for_service(service_id):
    return _stats_for_service_query(service_id).filter(func.date(Notification.created_at) == date.today()).all()


def fetch_todays_total_message_count(service_id):
    midnight = get_midnight(datetime.now(tz=pytz.utc))
    scheduled = (
        db.session.query(func.coalesce(func.sum(Job.notification_count), 0).label("count")).filter(
            Job.service_id == service_id,
            Job.job_status == JOB_STATUS_SCHEDULED,
            Job.scheduled_for >= midnight,
            Job.scheduled_for < midnight + timedelta(days=1),
        )
    ).first()

    result = (
        db.session.query(func.coalesce(func.count(Notification.id), 0).label("count")).filter(
            Notification.service_id == service_id,
            Notification.key_type != KEY_TYPE_TEST,
            Notification.created_at >= midnight,
        )
    ).first()

    return result.count + scheduled.count


def fetch_todays_total_sms_count(service_id):
    midnight = get_midnight(datetime.now(tz=pytz.utc))
    result = (
        db.session.query(func.count(Notification.id).label("total_sms_notifications"))
        .filter(
            Notification.service_id == service_id,
            Notification.key_type != KEY_TYPE_TEST,
            Notification.created_at > midnight,
            Notification.notification_type == "sms",
        )
        .first()
    )
    return 0 if result is None or result.total_sms_notifications is None else result.total_sms_notifications


def fetch_service_email_limit(service_id: uuid.UUID) -> int:
    return Service.query.get(service_id).message_limit


def fetch_todays_total_email_count(service_id: uuid.UUID) -> int:
    midnight = get_midnight(datetime.now(tz=pytz.utc))
    scheduled = (
        db.session.query(func.coalesce(func.sum(Job.notification_count), 0).label("total_scheduled_notifications")).filter(
            Job.service_id == service_id,
            Job.job_status == JOB_STATUS_SCHEDULED,
            Job.scheduled_for > midnight,
            Job.scheduled_for < midnight + timedelta(hours=23, minutes=59, seconds=59),
        )
    ).first()

    result = (
        db.session.query(func.coalesce(func.count(Notification.id), 0).label("total_email_notifications")).filter(
            Notification.service_id == service_id,
            Notification.key_type != KEY_TYPE_TEST,
            Notification.created_at > midnight,
            Notification.notification_type == "email",
        )
    ).first()

    return result.total_email_notifications + scheduled.total_scheduled_notifications


def _stats_for_service_query(service_id):
    return (
        db.session.query(
            Notification.notification_type,
            Notification.status,
            *([func.count(Notification.id).label("count")]),
        )
        .filter(
            Notification.service_id == service_id,
            Notification.key_type != KEY_TYPE_TEST,
        )
        .group_by(
            Notification.notification_type,
            Notification.status,
        )
    )


@statsd(namespace="dao")
def dao_fetch_todays_stats_for_all_services(include_from_test_key=True, only_active=True):
    today = convert_utc_to_local_timezone(datetime.utcnow())
    start_date = get_local_timezone_midnight_in_utc(today)
    end_date = get_local_timezone_midnight_in_utc(today + timedelta(days=1))

    subquery = (
        db.session.query(
            Notification.notification_type,
            Notification.status,
            Notification.service_id,
            func.count(Notification.id).label("count"),
        )
        .filter(Notification.created_at >= start_date, Notification.created_at < end_date)
        .group_by(Notification.notification_type, Notification.status, Notification.service_id)
    )

    if not include_from_test_key:
        subquery = subquery.filter(Notification.key_type != KEY_TYPE_TEST)

    subquery = subquery.subquery()

    query = (
        db.session.query(
            Service.id.label("service_id"),
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
        query = query.filter(Service.active)

    return query.all()


@transactional
@version_class(
    VersionOptions(ApiKey, must_write_history=False),
    VersionOptions(Service),
)
def dao_suspend_service(service_id):
    # have to eager load api keys so that we don't flush when we loop through them
    # to ensure that db.session still contains the models when it comes to creating history objects
    service = (
        Service.query.options(
            joinedload("api_keys"),
        )
        .filter(Service.id == service_id)
        .one()
    )

    for api_key in service.api_keys:
        if not api_key.expiry_date:
            api_key.expiry_date = datetime.utcnow()

    service.active = False


@transactional
@version_class(Service)
def dao_resume_service(service_id):
    service = Service.query.get(service_id)
    service.active = True


def dao_fetch_active_users_for_service(service_id):
    query = User.query.filter(User.services.any(id=service_id), User.state == "active")

    return query.all()


def dao_fetch_service_creator(service_id: uuid.UUID) -> User:
    service_history = Service.get_history_model()
    query = (
        User.query.join(service_history, User.id == service_history.created_by_id)
        .filter(service_history.id == service_id, service_history.version == 1)
        .one()
    )
    return query


def dao_fetch_service_ids_of_sensitive_services():
    sensitive_service_ids = Service.query.filter(Service.sensitive_service.is_(True)).with_entities(Service.id).all()
    return [str(service_id) for (service_id,) in sensitive_service_ids]
