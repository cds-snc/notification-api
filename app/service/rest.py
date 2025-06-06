import itertools
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from notifications_utils.clients.redis import (
    daily_limit_cache_key,
    near_daily_limit_cache_key,
    near_email_daily_limit_cache_key,
    near_sms_daily_limit_cache_key,
    over_daily_limit_cache_key,
    over_email_daily_limit_cache_key,
    over_sms_daily_limit_cache_key,
)
from psycopg2.errors import UniqueViolation
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound

from app import redis_store, salesforce_client
from app.annual_limit_utils import get_annual_limit_notifications_v2
from app.clients.salesforce.salesforce_engagement import ENGAGEMENT_STAGE_LIVE
from app.config import QueueNames
from app.dao import fact_notification_status_dao, notifications_dao
from app.dao.api_key_dao import (
    expire_api_key,
    get_model_api_keys,
    get_unsigned_secret,
    save_model_api_key,
)
from app.dao.dao_utils import dao_rollback
from app.dao.date_util import get_financial_year
from app.dao.fact_notification_status_dao import (
    fetch_delivered_notification_stats_by_month,
    fetch_monthly_template_usage_for_service,
    fetch_notification_status_for_service_by_month,
    fetch_notification_status_for_service_for_day,
    fetch_notification_status_for_service_for_today_and_7_previous_days,
    fetch_stats_for_all_services_by_date_range,
)
from app.dao.inbound_numbers_dao import dao_allocate_number_for_service
from app.dao.organisation_dao import dao_get_organisation_by_service_id
from app.dao.service_data_retention_dao import (
    fetch_service_data_retention,
    fetch_service_data_retention_by_id,
    fetch_service_data_retention_by_notification_type,
    insert_service_data_retention,
    update_service_data_retention,
)
from app.dao.service_email_reply_to_dao import (
    add_reply_to_email_address_for_service,
    archive_reply_to_email_address,
    dao_get_reply_to_by_id,
    dao_get_reply_to_by_service_id,
    update_reply_to_email_address,
)
from app.dao.service_safelist_dao import (
    dao_add_and_commit_safelisted_contacts,
    dao_fetch_service_safelist,
    dao_remove_service_safelist,
)
from app.dao.service_sms_sender_dao import (
    archive_sms_sender,
    dao_add_sms_sender_for_service,
    dao_get_service_sms_senders_by_id,
    dao_get_sms_senders_by_service_id,
    dao_update_service_sms_sender,
    update_existing_sms_sender_with_inbound_number,
)
from app.dao.services_dao import (
    dao_add_user_to_service,
    dao_archive_service,
    dao_create_service,
    dao_fetch_all_services,
    dao_fetch_all_services_by_user,
    dao_fetch_live_services_data,
    dao_fetch_service_by_id,
    dao_fetch_service_creator,
    dao_fetch_service_ids_of_sensitive_services,
    dao_fetch_todays_stats_for_all_services,
    dao_fetch_todays_stats_for_service,
    dao_remove_user_from_service,
    dao_resume_service,
    dao_suspend_service,
    dao_update_service,
    get_services_by_partial_name,
)
from app.dao.templates_dao import dao_get_template_by_id
from app.dao.users_dao import get_user_by_id
from app.errors import CannotRemoveUserError, InvalidRequest, UserAlreadyInServiceError, register_errors
from app.models import (
    EMAIL_TYPE,
    KEY_TYPE_NORMAL,
    LETTER_TYPE,
    MANAGE_SETTINGS,
    NOTIFICATION_CANCELLED,
    SMS_TYPE,
    EmailBranding,
    LetterBranding,
    NotificationType,
    Permission,
    Service,
)
from app.notifications.process_notifications import (
    persist_notification,
    send_notification_to_queue,
)
from app.schema_validation import validate
from app.schemas import (
    api_key_schema,
    detailed_service_schema,
    email_data_request_schema,
    notification_with_template_schema,
    notifications_filter_schema,
    service_schema,
)
from app.service import statistics
from app.service.send_notification import send_one_off_notification
from app.service.sender import send_notification_to_service_users
from app.service.service_data_retention_schema import (
    add_service_data_retention_request,
    update_service_data_retention_request,
)
from app.service.service_senders_schema import (
    add_service_email_reply_to_request,
    add_service_sms_sender_request,
)
from app.service.utils import (
    get_organisation_id_from_crm_org_notes,
    get_safelist_objects,
)
from app.user.users_schema import post_set_permissions_schema
from app.utils import pagination_links

service_blueprint = Blueprint("service", __name__)

register_errors(service_blueprint)

# TODO: FF_ANNUAL_LIMIT - Remove once logic is consolidated in the annual_limit_client
ANNUAL_LIMIT_SMS_OVER_NEAR_STATUS_FIELDS = ["near_sms_limit", "near_email_limit"]
ANNUAL_LIMIT_EMAIL_OVER_NEAR_STATUS_FIELDS = ["over_email_limit", "near_email_limit"]


@service_blueprint.errorhandler(IntegrityError)
def handle_integrity_error(exc):
    """
    Handle integrity errors caused by the unique constraint on ix_organisation_name
    """
    if any(
        'duplicate key value violates unique constraint "{}"'.format(constraint) in str(exc)
        for constraint in {"services_name_key", "services_email_from_key"}
    ):
        return (
            jsonify(
                result="error",
                message={
                    "name": ["Duplicate service name '{}'".format(exc.params.get("name", exc.params.get("email_from", "")))]
                },
            ),
            400,
        )
    current_app.logger.exception(exc)
    return jsonify(result="error", message="Internal server error"), 500


@service_blueprint.route("", methods=["GET"])
def get_services():
    only_active = request.args.get("only_active") == "True"
    detailed = request.args.get("detailed") == "True"
    user_id = request.args.get("user_id", None)
    include_from_test_key = request.args.get("include_from_test_key", "True") != "False"

    # If start and end date are not set, we are expecting today's stats.
    today = str(datetime.utcnow().date())

    start_date = datetime.strptime(request.args.get("start_date", today), "%Y-%m-%d").date()
    end_date = datetime.strptime(request.args.get("end_date", today), "%Y-%m-%d").date()

    if user_id:
        services = dao_fetch_all_services_by_user(user_id, only_active)
    elif detailed:
        result = jsonify(
            data=get_detailed_services(
                start_date=start_date,
                end_date=end_date,
                only_active=only_active,
                include_from_test_key=include_from_test_key,
            )
        )
        return result
    else:
        services = dao_fetch_all_services(only_active)
    data = service_schema.dump(services, many=True)
    return jsonify(data=data)


@service_blueprint.route("/find-services-by-name", methods=["GET"])
def find_services_by_name():
    service_name = request.args.get("service_name")
    if not service_name:
        errors = {"service_name": ["Missing data for required field."]}
        raise InvalidRequest(errors, status_code=400)
    fetched_services = get_services_by_partial_name(service_name)
    data = [service.serialize_for_org_dashboard() for service in fetched_services]
    return jsonify(data=data), 200


@service_blueprint.route("/live-services-data", methods=["GET"])
def get_live_services_data():
    filter_heartbeats = request.args.get("filter_heartbeats", None) == "True"
    data = dao_fetch_live_services_data(filter_heartbeats=filter_heartbeats)
    return jsonify(data=data)


@service_blueprint.route("/delivered-notifications-stats-by-month-data", methods=["GET"])
def get_delivered_notification_stats_by_month_data():
    filter_heartbeats = request.args.get("filter_heartbeats", None) == "True"
    return jsonify(data=fetch_delivered_notification_stats_by_month(filter_heartbeats=filter_heartbeats))


@service_blueprint.route("/<uuid:service_id>", methods=["GET"])
def get_service_by_id(service_id):
    if request.args.get("detailed") == "True":
        data = get_detailed_service(service_id, today_only=request.args.get("today_only") == "True")
    else:
        fetched = dao_fetch_service_by_id(service_id)

        data = service_schema.dump(fetched)
    return jsonify(data=data)


@service_blueprint.route("/<uuid:service_id>/statistics")
def get_service_notification_statistics(service_id):
    return jsonify(
        data=get_service_statistics(
            service_id,
            request.args.get("today_only") == "True",
            int(request.args.get("limit_days", 7)),
        )
    )


@service_blueprint.route("", methods=["POST"])
def create_service():
    data = request.get_json()
    data["sms_daily_limit"] = data.get(
        "sms_daily_limit", 1000
    )  # TODO this is to support current admin. can remove after admin sends an sms_daily_limit

    if not data.get("user_id"):
        errors = {"user_id": ["Missing data for required field."]}
        raise InvalidRequest(errors, status_code=400)
    data.pop("service_domain", None)

    # validate json with marshmallow
    service_schema.load(data)

    user = get_user_by_id(data.pop("user_id"))

    # unpack valid json into service object
    valid_service = Service.from_json(data)

    organisation_id = (
        get_organisation_id_from_crm_org_notes(data["organisation_notes"])
        if ("organisation_notes" in data and data["organisation_notes"])
        else None
    )

    dao_create_service(valid_service, user, organisation_id=organisation_id)

    if current_app.config["FF_SALESFORCE_CONTACT"]:
        try:
            salesforce_client.engagement_create(valid_service, user)
        except Exception as e:
            current_app.logger.exception(e)

    return jsonify(data=service_schema.dump(valid_service)), 201


# flake8: noqa: C901
@service_blueprint.route("/<uuid:service_id>", methods=["POST"])
def update_service(service_id):
    req_json = request.get_json()
    fetched_service = dao_fetch_service_by_id(service_id)
    # Capture the status change here as Marshmallow changes this later
    service_going_live = fetched_service.restricted and not req_json.get("restricted", True)
    service_name_changed = fetched_service.name != req_json.get("name", fetched_service.name)
    message_limit_changed = fetched_service.message_limit != req_json.get("message_limit", fetched_service.message_limit)
    sms_limit_changed = fetched_service.sms_daily_limit != req_json.get("sms_daily_limit", fetched_service.sms_daily_limit)
    email_annual_limit_changed = fetched_service.email_annual_limit != req_json.get(
        "email_annual_limit", fetched_service.email_annual_limit
    )
    sms_annual_limit_changed = fetched_service.sms_annual_limit != req_json.get(
        "sms_annual_limit", fetched_service.sms_annual_limit
    )
    current_data = dict(service_schema.dump(fetched_service).items())

    current_data.update(request.get_json())

    service = service_schema.load(current_data)

    if "email_branding" in req_json:
        email_branding_id = req_json["email_branding"]
        service.email_branding = None if not email_branding_id else EmailBranding.query.get(email_branding_id)
    if "letter_branding" in req_json:
        letter_branding_id = req_json["letter_branding"]
        service.letter_branding = None if not letter_branding_id else LetterBranding.query.get(letter_branding_id)

    dao_update_service(service)

    if message_limit_changed:
        redis_store.delete(daily_limit_cache_key(service_id))
        redis_store.delete(near_daily_limit_cache_key(service_id))
        redis_store.delete(over_daily_limit_cache_key(service_id))
        redis_store.delete(near_email_daily_limit_cache_key(service_id))
        redis_store.delete(over_email_daily_limit_cache_key(service_id))
        if not fetched_service.restricted:
            _warn_service_users_about_message_limit_changed(service_id, current_data)
    if sms_limit_changed:
        redis_store.delete(near_sms_daily_limit_cache_key(service_id))
        redis_store.delete(over_sms_daily_limit_cache_key(service_id))
        if not fetched_service.restricted:
            _warn_service_users_about_sms_limit_changed(service_id, current_data)
    if sms_annual_limit_changed:
        _warn_service_users_about_annual_limit_change(service, SMS_TYPE)
        # TODO: abstract this in the annual_limits_client
        redis_store.delete_hash_fields(f"annual-limit:{service_id}:status", ANNUAL_LIMIT_SMS_OVER_NEAR_STATUS_FIELDS)
    if email_annual_limit_changed:
        _warn_service_users_about_annual_limit_change(service, EMAIL_TYPE)
        # TODO: abstract this in the annual_limits_client
        redis_store.delete_hash_fields(f"annual-limit:{service_id}:status", ANNUAL_LIMIT_EMAIL_OVER_NEAR_STATUS_FIELDS)

    if service_going_live:
        _warn_services_users_about_going_live(service_id, current_data)

    if current_app.config["FF_SALESFORCE_CONTACT"]:
        try:
            if service_going_live:
                # Two scenarios, if there is a user that has requested to go live, we will use that user
                # to create a Contact/Engagment pair between Notify and Salesforce.
                # If by any chance there is no tracked request to a user, Notify will try to identify the user
                # that created the service and then create a Contact/Engagment relationship.
                if service.go_live_user_id:
                    user = get_user_by_id(service.go_live_user_id)
                else:
                    user = dao_fetch_service_creator(service.id)
                salesforce_client.engagement_update(service, user, {"StageName": ENGAGEMENT_STAGE_LIVE})
            elif service_name_changed:
                user = dao_fetch_service_creator(service.id)
                salesforce_client.engagement_update(service, user, {"Name": service.name})
        except Exception as e:
            current_app.logger.exception(e)

    return jsonify(data=service_schema.dump(fetched_service)), 200


def _warn_service_users_about_message_limit_changed(service_id, data):
    send_notification_to_service_users(
        service_id=service_id,
        template_id=current_app.config["DAILY_EMAIL_LIMIT_UPDATED_TEMPLATE_ID"],
        personalisation={
            "service_name": data["name"],
            "message_limit_en": "{:,}".format(data["message_limit"]),
            "message_limit_fr": "{:,}".format(data["message_limit"]).replace(",", " "),
        },
        include_user_fields=["name"],
    )


def _warn_service_users_about_sms_limit_changed(service_id, data):
    send_notification_to_service_users(
        service_id=service_id,
        template_id=current_app.config["DAILY_SMS_LIMIT_UPDATED_TEMPLATE_ID"],
        personalisation={
            "service_name": data["name"],
            "message_limit_en": "{:,}".format(data["sms_daily_limit"]),
            "message_limit_fr": "{:,}".format(data["sms_daily_limit"]).replace(",", " "),
        },
        include_user_fields=["name"],
    )


def _warn_service_users_about_annual_limit_change(service: Service, notification_type: NotificationType):
    send_notification_to_service_users(
        service_id=service.id,
        template_id=current_app.config["ANNUAL_LIMIT_UPDATED_TEMPLATE_ID"],
        personalisation={
            "service_name": service.name,
            "message_type_en": "emails" if notification_type == EMAIL_TYPE else "text messages",
            "message_type_fr": "courriels" if notification_type == EMAIL_TYPE else "messages texte",
            "message_limit_en": "{:,}".format(service.email_annual_limit)
            if notification_type == EMAIL_TYPE
            else "{:,}".format(service.sms_annual_limit),
            "message_limit_fr": "{:,}".format(
                service.email_annual_limit if notification_type == EMAIL_TYPE else service.sms_annual_limit
            ).replace(",", " "),
            "hyperlink_to_page_en": f"{current_app.config['ADMIN_BASE_URL']}/services/{service.id}/monthly",
            "hyperlink_to_page_fr": f"{current_app.config['ADMIN_BASE_URL']}/services/{service.id}/monthly?lang=fr",
        },
        include_user_fields=["name"],
    )


def _warn_services_users_about_going_live(service_id, data):
    send_notification_to_service_users(
        service_id=service_id,
        template_id=current_app.config["SERVICE_NOW_LIVE_TEMPLATE_ID"],
        personalisation={
            "service_name": data["name"],
            "contact_us_url": f"{current_app.config['ADMIN_BASE_URL']}/contact",
            "signin_url": f"{current_app.config['ADMIN_BASE_URL']}/sign-in",
            "message_limit_en": "{:,}".format(data["message_limit"]),
            "message_limit_fr": "{:,}".format(data["message_limit"]).replace(",", " "),
        },
        include_user_fields=["name"],
    )


@service_blueprint.route("/<uuid:service_id>/api-key", methods=["POST"])
def create_api_key(service_id=None):
    fetched_service = dao_fetch_service_by_id(service_id=service_id)
    valid_api_key = api_key_schema.load(request.get_json())
    valid_api_key.service = fetched_service
    save_model_api_key(valid_api_key)
    unsigned_api_key = get_unsigned_secret(valid_api_key.id)

    # prefix the API key so they keys can be easily identified for security scanning
    keydata = {
        "key": unsigned_api_key,
        "key_name": current_app.config["API_KEY_PREFIX"] + valid_api_key.name,
    }

    return jsonify(data=keydata), 201


@service_blueprint.route("/<uuid:service_id>/api-key/revoke/<uuid:api_key_id>", methods=["POST"])
def revoke_api_key(service_id, api_key_id):
    expire_api_key(service_id=service_id, api_key_id=api_key_id)
    return jsonify(), 202


@service_blueprint.route("/<uuid:service_id>/api-keys", methods=["GET"])
@service_blueprint.route("/<uuid:service_id>/api-keys/<uuid:key_id>", methods=["GET"])
def get_api_keys(service_id, key_id=None):
    dao_fetch_service_by_id(service_id=service_id)

    try:
        if key_id:
            api_keys = [get_model_api_keys(service_id=service_id, id=key_id)]
        else:
            api_keys = get_model_api_keys(service_id=service_id)
    except NoResultFound:
        error = "API key not found for id: {}".format(service_id)
        raise InvalidRequest(error, status_code=404)

    return jsonify(apiKeys=api_key_schema.dump(api_keys, many=True)), 200


@service_blueprint.route("/<uuid:service_id>/users", methods=["GET"])
def get_users_for_service(service_id):
    fetched = dao_fetch_service_by_id(service_id)
    return jsonify(data=[x.serialize() for x in fetched.users])


@service_blueprint.route("/<uuid:service_id>/users/<user_id>", methods=["POST"])
def add_user_to_service(service_id, user_id):
    service = dao_fetch_service_by_id(service_id)
    user = get_user_by_id(user_id=user_id)

    if user in service.users:
        message = "User id: {} already part of service id: {}".format(user_id, service_id)
        current_app.logger.info(message)
        raise UserAlreadyInServiceError(status_code=409, message=message)

    data = request.get_json()
    validate(data, post_set_permissions_schema)

    permissions = [Permission(service_id=service_id, user_id=user_id, permission=p["permission"]) for p in data["permissions"]]
    folder_permissions = data.get("folder_permissions", [])

    try:
        dao_add_user_to_service(service, user, permissions, folder_permissions)
    except UniqueViolation:
        message = f"UniqueViolation: User id: {user_id} already part of service id: {service_id}"
        current_app.logger.info(message)
        raise UserAlreadyInServiceError(status_code=409, message=message)
    except IntegrityError as e:
        if isinstance(e.orig, UniqueViolation):
            message = f"UniqueViolation: User id: {user_id} already part of service id: {service_id}"
            current_app.logger.info(message)
            raise UserAlreadyInServiceError(status_code=409, message=message)
        else:
            raise
    except Exception as e:
        current_app.logger.exception(e)
        raise InvalidRequest("An error occurred while adding user to service", status_code=500)

    data = service_schema.dump(service)

    if current_app.config["FF_SALESFORCE_CONTACT"]:
        try:
            salesforce_client.engagement_add_contact_role(service, user)
        except Exception as e:
            current_app.logger.exception(e)

    return jsonify(data=data), 201


@service_blueprint.route("/<uuid:service_id>/users/<user_id>", methods=["DELETE"])
def remove_user_from_service(service_id, user_id):
    service = dao_fetch_service_by_id(service_id)
    user = get_user_by_id(user_id=user_id)
    users_with_manage_settings_perm = service.get_users_with_permission(MANAGE_SETTINGS)

    if user not in service.users:
        error = "User not found"
        raise InvalidRequest(error, status_code=404)

    elif len(service.users) == 1:
        error = "You cannot remove the only user for a service"
        raise CannotRemoveUserError(message=error)

    elif len(service.users) == 2:
        error = "SERVICE_CANNOT_HAVE_LT_2_MEMBERS"
        raise CannotRemoveUserError(message=error)

    elif user in users_with_manage_settings_perm and len(users_with_manage_settings_perm) <= 1:
        error = "SERVICE_NEEDS_USER_W_MANAGE_SETTINGS_PERM"
        raise CannotRemoveUserError(message=error)

    dao_remove_user_from_service(service, user)

    if current_app.config["FF_SALESFORCE_CONTACT"]:
        try:
            salesforce_client.engagement_delete_contact_role(service, user)
        except Exception as e:
            current_app.logger.exception(e)

    return jsonify({}), 204


# This is placeholder get method until more thought
# goes into how we want to fetch and view various items in history
# tables. This is so product owner can pass stories as done
@service_blueprint.route("/<uuid:service_id>/history", methods=["GET"])
def get_service_history(service_id):
    from app.models import ApiKey, Service, TemplateHistory
    from app.schemas import (
        api_key_history_schema,
        service_history_schema,
        template_history_schema,
    )

    service_history = Service.get_history_model().query.filter_by(id=service_id).all()
    service_data = service_history_schema.dump(service_history, many=True)
    api_key_history = ApiKey.get_history_model().query.filter_by(service_id=service_id).all()
    api_keys_data = api_key_history_schema.dump(api_key_history, many=True)

    template_history = TemplateHistory.query.filter_by(service_id=service_id).all()
    template_data = template_history_schema.dump(template_history, many=True)

    data = {
        "service_history": service_data,
        "api_key_history": api_keys_data,
        "template_history": template_data,
        "events": [],
    }

    return jsonify(data=data)


@service_blueprint.route("/<uuid:service_id>/notifications", methods=["GET"])
def get_all_notifications_for_service(service_id):
    data = notifications_filter_schema.load(request.args)
    if data.get("to"):
        notification_type = data.get("template_type")[0] if data.get("template_type") else None
        return search_for_notification_by_to_field(
            service_id=service_id,
            search_term=data["to"],
            statuses=data.get("status"),
            notification_type=notification_type,
        )
    page = data["page"] if "page" in data else 1
    page_size = data["page_size"] if "page_size" in data else current_app.config.get("PAGE_SIZE")
    limit_days = data.get("limit_days")
    include_jobs = data.get("include_jobs", True)
    include_from_test_key = data.get("include_from_test_key", False)
    include_one_off = data.get("include_one_off", True)

    count_pages = data.get("count_pages", True)
    format_for_csv = data.get("format_for_csv", False)

    pagination = notifications_dao.get_notifications_for_service(
        service_id,
        filter_dict=data,
        page=page,
        page_size=page_size,
        count_pages=count_pages,
        limit_days=limit_days,
        include_jobs=include_jobs,
        include_from_test_key=include_from_test_key,
        include_one_off=include_one_off,
        format_for_csv=format_for_csv,
    )

    kwargs = request.args.to_dict()
    kwargs["service_id"] = service_id

    if format_for_csv:
        notifications = [notification.serialize_for_csv() for notification in pagination.items]
    else:
        notifications = notification_with_template_schema.dump(pagination.items, many=True)
    return (
        jsonify(
            notifications=notifications,
            page_size=page_size,
            total=pagination.total,
            links=pagination_links(pagination, ".get_all_notifications_for_service", **kwargs),
        ),
        200,
    )


@service_blueprint.route("/<uuid:service_id>/notifications/<uuid:notification_id>", methods=["GET"])
def get_notification_for_service(service_id, notification_id):
    notification = notifications_dao.get_notification_with_personalisation(service_id, notification_id, key_type=None)
    if notification is not None:
        return jsonify(notification_with_template_schema.dump(notification)), 200
    else:
        return jsonify(result="error", message="Notification not found in database"), 404


@service_blueprint.route("/<uuid:service_id>/notifications/<uuid:notification_id>/cancel", methods=["POST"])
def cancel_notification_for_service(service_id, notification_id):
    notification = notifications_dao.get_notification_by_id(notification_id, service_id)

    if not notification:
        raise InvalidRequest("Notification not found", status_code=404)
    elif notification.notification_type != LETTER_TYPE:
        raise InvalidRequest(
            "Notification cannot be cancelled - only letters can be cancelled",
            status_code=400,
        )

    updated_notification = notifications_dao.update_notification_status_by_id(
        notification_id,
        NOTIFICATION_CANCELLED,
    )

    return (
        jsonify(notification_with_template_schema.dump(updated_notification)),
        200,
    )


def search_for_notification_by_to_field(service_id, search_term, statuses, notification_type):
    results = notifications_dao.dao_get_notifications_by_to_field(
        service_id=service_id,
        search_term=search_term,
        statuses=statuses,
        notification_type=notification_type,
    )
    return (
        jsonify(notifications=notification_with_template_schema.dump(results, many=True)),
        200,
    )


@service_blueprint.route("/<uuid:service_id>/notifications/monthly", methods=["GET"])
def get_monthly_notification_stats(service_id):
    # check service_id validity
    dao_fetch_service_by_id(service_id)

    try:
        year = int(request.args.get("year", "NaN"))
    except ValueError:
        raise InvalidRequest("Year must be a number", status_code=400)

    start_date, end_date = get_financial_year(year)

    data = statistics.create_empty_monthly_notification_status_stats_dict(year)

    stats = fetch_notification_status_for_service_by_month(start_date, end_date, service_id)
    statistics.add_monthly_notification_status_stats(data, stats)

    now = datetime.now(timezone.utc)
    # end_date doesn't have tzinfo, so we need to remove it from now
    end_date_now = now.replace(tzinfo=None)
    # TODO FF_ANNUAL_LIMIT removal
    if not current_app.config["FF_ANNUAL_LIMIT"] and end_date > end_date_now:
        todays_deltas = fetch_notification_status_for_service_for_day(now, service_id=service_id)
        statistics.add_monthly_notification_status_stats(data, todays_deltas)

    return jsonify(data=data)


def get_detailed_service(service_id, today_only=False):
    service = dao_fetch_service_by_id(service_id)

    service.statistics = get_service_statistics(service_id, today_only)
    return detailed_service_schema.dump(service)


def get_service_statistics(service_id, today_only, limit_days=7):
    # today_only flag is used by the send page to work out if the service will exceed their daily usage by sending a job
    if today_only:
        stats = dao_fetch_todays_stats_for_service(service_id)
    else:
        stats = fetch_notification_status_for_service_for_today_and_7_previous_days(service_id, limit_days=limit_days)

    return statistics.format_statistics(stats)


def get_detailed_services(start_date, end_date, only_active=False, include_from_test_key=True):
    if start_date == datetime.utcnow().date():
        stats = dao_fetch_todays_stats_for_all_services(include_from_test_key=include_from_test_key, only_active=only_active)
    else:
        stats = fetch_stats_for_all_services_by_date_range(
            start_date=start_date,
            end_date=end_date,
            include_from_test_key=include_from_test_key,
        )
    results = []
    for service_id, rows in itertools.groupby(stats, lambda x: x.service_id):
        rows = list(rows)
        s = statistics.format_statistics(rows)
        results.append(
            {
                "id": str(rows[0].service_id),
                "name": rows[0].name,
                "notification_type": rows[0].notification_type,
                "research_mode": rows[0].research_mode,
                "restricted": rows[0].restricted,
                "active": rows[0].active,
                "created_at": rows[0].created_at,
                "statistics": s,
            }
        )
    return results


@service_blueprint.route("/<uuid:service_id>/safelist", methods=["GET"])
def get_safelist(service_id):
    from app.models import EMAIL_TYPE, MOBILE_TYPE

    service = dao_fetch_service_by_id(service_id)

    if not service:
        raise InvalidRequest("Service does not exist", status_code=404)

    safelist = dao_fetch_service_safelist(service.id)
    return jsonify(
        email_addresses=[item.recipient for item in safelist if item.recipient_type == EMAIL_TYPE],
        phone_numbers=[item.recipient for item in safelist if item.recipient_type == MOBILE_TYPE],
    )


@service_blueprint.route("/<uuid:service_id>/safelist", methods=["PUT"])
def update_safelist(service_id):
    # doesn't commit so if there are any errors, we preserve old values in db
    dao_remove_service_safelist(service_id)
    try:
        safelist_objs = get_safelist_objects(service_id, request.get_json())
    except ValueError as e:
        current_app.logger.exception(e)
        dao_rollback()
        msg = "{} is not a valid email address or phone number".format(str(e))
        raise InvalidRequest(msg, 400)
    else:
        dao_add_and_commit_safelisted_contacts(safelist_objs)
        return "", 204


@service_blueprint.route("/<uuid:service_id>/archive", methods=["POST"])
def archive_service(service_id):
    """
    When a service is archived the service is made inactive, templates are archived and api keys are revoked.
    There is no coming back from this operation.
    :param service_id:
    :return:
    """
    service = dao_fetch_service_by_id(service_id)

    if service.active:
        dao_archive_service(service.id)
        if current_app.config["FF_SALESFORCE_CONTACT"]:
            try:
                salesforce_client.engagement_close(service)
            except Exception as e:
                current_app.logger.exception(e)

    return "", 204


@service_blueprint.route("/<uuid:service_id>/suspend", methods=["POST"])
def suspend_service(service_id):
    """
    Suspending a service will mark the service as inactive and revoke API keys.
    :param service_id:
    :return:
    """
    service = dao_fetch_service_by_id(service_id)

    if service.active:
        dao_suspend_service(service.id)

    return "", 204


@service_blueprint.route("/<uuid:service_id>/resume", methods=["POST"])
def resume_service(service_id):
    """
    Resuming a service that has been suspended will mark the service as active.
    The service will need to re-create API keys
    :param service_id:
    :return:
    """
    service = dao_fetch_service_by_id(service_id)

    if not service.active:
        dao_resume_service(service.id)

    return "", 204


@service_blueprint.route("/<uuid:service_id>/notifications/templates_usage/monthly", methods=["GET"])
def get_monthly_template_usage(service_id):
    try:
        start_date, end_date = get_financial_year(int(request.args.get("year", "NaN")))
        data = fetch_monthly_template_usage_for_service(start_date=start_date, end_date=end_date, service_id=service_id)
        stats = list()
        for i in data:
            stats.append(
                {
                    "template_id": str(i.template_id),
                    "name": i.name,
                    "type": i.template_type,
                    "month": i.month,
                    "year": i.year,
                    "count": i.count,
                    "is_precompiled_letter": i.is_precompiled_letter,
                }
            )

        return jsonify(stats=stats), 200
    except ValueError:
        raise InvalidRequest("Year must be a number", status_code=400)


@service_blueprint.route("/<uuid:service_id>/send-notification", methods=["POST"])
def create_one_off_notification(service_id):
    resp = send_one_off_notification(service_id, request.get_json())
    return jsonify(resp), 201


@service_blueprint.route("/<uuid:service_id>/send-pdf-letter", methods=["POST"])
def create_pdf_letter(service_id):
    pass


@service_blueprint.route("/<uuid:service_id>/email-reply-to", methods=["GET"])
def get_email_reply_to_addresses(service_id):
    result = dao_get_reply_to_by_service_id(service_id)
    return jsonify([i.serialize() for i in result]), 200


@service_blueprint.route("/<uuid:service_id>/email-reply-to/<uuid:reply_to_id>", methods=["GET"])
def get_email_reply_to_address(service_id, reply_to_id):
    result = dao_get_reply_to_by_id(service_id=service_id, reply_to_id=reply_to_id)
    return jsonify(result.serialize()), 200


@service_blueprint.route("/<uuid:service_id>/email-reply-to/verify", methods=["POST"])
def verify_reply_to_email_address(service_id):
    email_address = email_data_request_schema.load(request.get_json())
    check_if_reply_to_address_already_in_use(service_id, email_address["email"])
    template = dao_get_template_by_id(current_app.config["REPLY_TO_EMAIL_ADDRESS_VERIFICATION_TEMPLATE_ID"])
    notify_service = Service.query.get(current_app.config["NOTIFY_SERVICE_ID"])
    saved_notification = persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient=email_address["email"],
        service=notify_service,
        personalisation="",
        notification_type=template.template_type,
        api_key_id=None,
        key_type=KEY_TYPE_NORMAL,
        reply_to_text=notify_service.get_default_reply_to_email_address(),
    )

    send_notification_to_queue(saved_notification, False, queue=QueueNames.NOTIFY)

    return jsonify(data={"id": saved_notification.id}), 201


@service_blueprint.route("/<uuid:service_id>/email-reply-to", methods=["POST"])
def add_service_reply_to_email_address(service_id):
    # validate the service exists, throws ResultNotFound exception.
    dao_fetch_service_by_id(service_id)
    form = validate(request.get_json(), add_service_email_reply_to_request)
    check_if_reply_to_address_already_in_use(service_id, form["email_address"])
    new_reply_to = add_reply_to_email_address_for_service(
        service_id=service_id,
        email_address=form["email_address"],
        is_default=form.get("is_default", True),
    )
    return jsonify(data=new_reply_to.serialize()), 201


@service_blueprint.route("/<uuid:service_id>/email-reply-to/<uuid:reply_to_email_id>", methods=["POST"])
def update_service_reply_to_email_address(service_id, reply_to_email_id):
    # validate the service exists, throws ResultNotFound exception.
    dao_fetch_service_by_id(service_id)
    form = validate(request.get_json(), add_service_email_reply_to_request)
    new_reply_to = update_reply_to_email_address(
        service_id=service_id,
        reply_to_id=reply_to_email_id,
        email_address=form["email_address"],
        is_default=form.get("is_default", True),
    )
    return jsonify(data=new_reply_to.serialize()), 200


@service_blueprint.route(
    "/<uuid:service_id>/email-reply-to/<uuid:reply_to_email_id>/archive",
    methods=["POST"],
)
def delete_service_reply_to_email_address(service_id, reply_to_email_id):
    archived_reply_to = archive_reply_to_email_address(service_id, reply_to_email_id)

    return jsonify(data=archived_reply_to.serialize()), 200


@service_blueprint.route("/<uuid:service_id>/letter-contact", methods=["GET"])
def get_letter_contacts(service_id):
    pass


@service_blueprint.route("/<uuid:service_id>/letter-contact/<uuid:letter_contact_id>", methods=["GET"])
def get_letter_contact_by_id(service_id, letter_contact_id):
    pass


@service_blueprint.route("/<uuid:service_id>/letter-contact", methods=["POST"])
def add_service_letter_contact(service_id):
    pass


@service_blueprint.route("/<uuid:service_id>/letter-contact/<uuid:letter_contact_id>", methods=["POST"])
def update_service_letter_contact(service_id, letter_contact_id):
    pass


@service_blueprint.route(
    "/<uuid:service_id>/letter-contact/<uuid:letter_contact_id>/archive",
    methods=["POST"],
)
def delete_service_letter_contact(service_id, letter_contact_id):
    pass


@service_blueprint.route("/<uuid:service_id>/sms-sender", methods=["POST"])
def add_service_sms_sender(service_id):
    dao_fetch_service_by_id(service_id)
    form = validate(request.get_json(), add_service_sms_sender_request)
    inbound_number_id = form.get("inbound_number_id", None)
    sms_sender = form.get("sms_sender")

    if inbound_number_id:
        updated_number = dao_allocate_number_for_service(service_id=service_id, inbound_number_id=inbound_number_id)
        # the sms_sender in the form is not set, use the inbound number
        sms_sender = updated_number.number
        existing_sms_sender = dao_get_sms_senders_by_service_id(service_id)
        # we don't want to create a new sms sender for the service if we are allocating an inbound number.
        if len(existing_sms_sender) == 1:
            update_existing_sms_sender = existing_sms_sender[0]
            new_sms_sender = update_existing_sms_sender_with_inbound_number(
                service_sms_sender=update_existing_sms_sender,
                sms_sender=sms_sender,
                inbound_number_id=inbound_number_id,
            )

            return jsonify(new_sms_sender.serialize()), 201

    new_sms_sender = dao_add_sms_sender_for_service(
        service_id=service_id,
        sms_sender=sms_sender,
        is_default=form["is_default"],
        inbound_number_id=inbound_number_id,
    )
    return jsonify(new_sms_sender.serialize()), 201


@service_blueprint.route("/<uuid:service_id>/sms-sender/<uuid:sms_sender_id>", methods=["POST"])
def update_service_sms_sender(service_id, sms_sender_id):
    form = validate(request.get_json(), add_service_sms_sender_request)

    sms_sender_to_update = dao_get_service_sms_senders_by_id(service_id=service_id, service_sms_sender_id=sms_sender_id)
    if sms_sender_to_update.inbound_number_id and form["sms_sender"] != sms_sender_to_update.sms_sender:
        raise InvalidRequest(
            "You can not change the inbound number for service {}".format(service_id),
            status_code=400,
        )

    new_sms_sender = dao_update_service_sms_sender(
        service_id=service_id,
        service_sms_sender_id=sms_sender_id,
        is_default=form["is_default"],
        sms_sender=form["sms_sender"],
    )
    return jsonify(new_sms_sender.serialize()), 200


@service_blueprint.route("/<uuid:service_id>/sms-sender/<uuid:sms_sender_id>/archive", methods=["POST"])
def delete_service_sms_sender(service_id, sms_sender_id):
    sms_sender = archive_sms_sender(service_id, sms_sender_id)

    return jsonify(data=sms_sender.serialize()), 200


@service_blueprint.route("/<uuid:service_id>/sms-sender/<uuid:sms_sender_id>", methods=["GET"])
def get_service_sms_sender_by_id(service_id, sms_sender_id):
    sms_sender = dao_get_service_sms_senders_by_id(service_id=service_id, service_sms_sender_id=sms_sender_id)
    return jsonify(sms_sender.serialize()), 200


@service_blueprint.route("/<uuid:service_id>/sms-sender", methods=["GET"])
def get_service_sms_senders_for_service(service_id):
    sms_senders = dao_get_sms_senders_by_service_id(service_id=service_id)
    return jsonify([sms_sender.serialize() for sms_sender in sms_senders]), 200


@service_blueprint.route("/<uuid:service_id>/organisation", methods=["GET"])
def get_organisation_for_service(service_id):
    organisation = dao_get_organisation_by_service_id(service_id=service_id)
    return jsonify(organisation.serialize() if organisation else {}), 200


@service_blueprint.route("/unique", methods=["GET"])
def _is_service_name_unique():
    service_id, name, email_from = _check_request_args(request)

    name_exists = Service.query.filter_by(name=name).first()

    email_from_exists = Service.query.filter(Service.email_from == email_from, Service.id != service_id).first()

    result = not (name_exists or email_from_exists)
    return jsonify(result=result), 200


@service_blueprint.route("/name/unique", methods=["GET"])
def is_service_name_unique():
    service_id, name = check_unique_name_request_args(request)

    name_exists = Service.query.filter(func.lower(Service.name) == func.lower(name), Service.id != service_id).first()

    result = not name_exists
    return jsonify(result=result), 200


@service_blueprint.route("/email-from/unique", methods=["GET"])
def is_service_email_from_unique():
    service_id, email_from = check_unique_email_from_request_args(request)

    email_from_exists = Service.query.filter(
        func.lower(Service.email_from) == func.lower(email_from),
        Service.id != service_id,
    ).first()

    result = not email_from_exists
    return jsonify(result=result), 200


@service_blueprint.route("/<uuid:service_id>/data-retention", methods=["GET"])
def get_data_retention_for_service(service_id):
    data_retention_list = fetch_service_data_retention(service_id)
    return (
        jsonify([data_retention.serialize() for data_retention in data_retention_list]),
        200,
    )


@service_blueprint.route(
    "/<uuid:service_id>/data-retention/notification-type/<notification_type>",
    methods=["GET"],
)
def get_data_retention_for_service_notification_type(service_id, notification_type):
    data_retention = fetch_service_data_retention_by_notification_type(service_id, notification_type)
    return jsonify(data_retention.serialize() if data_retention else {}), 200


@service_blueprint.route("/<uuid:service_id>/data-retention/<uuid:data_retention_id>", methods=["GET"])
def get_data_retention_for_service_by_id(service_id, data_retention_id):
    data_retention = fetch_service_data_retention_by_id(service_id, data_retention_id)
    return jsonify(data_retention.serialize() if data_retention else {}), 200


@service_blueprint.route("/<uuid:service_id>/data-retention", methods=["POST"])
def create_service_data_retention(service_id):
    form = validate(request.get_json(), add_service_data_retention_request)
    try:
        new_data_retention = insert_service_data_retention(
            service_id=service_id,
            notification_type=form.get("notification_type"),
            days_of_retention=form.get("days_of_retention"),
        )
    except IntegrityError:
        raise InvalidRequest(
            message="Service already has data retention for {} notification type".format(form.get("notification_type")),
            status_code=400,
        )

    return jsonify(result=new_data_retention.serialize()), 201


@service_blueprint.route("/<uuid:service_id>/annual-limit-stats", methods=["GET"])
def get_annual_limit_stats(service_id):
    data_retention = get_annual_limit_notifications_v2(service_id)
    return data_retention if data_retention else {}, 200


@service_blueprint.route("/<uuid:service_id>/data-retention/<uuid:data_retention_id>", methods=["POST"])
def modify_service_data_retention(service_id, data_retention_id):
    form = validate(request.get_json(), update_service_data_retention_request)

    update_count = update_service_data_retention(
        service_data_retention_id=data_retention_id,
        service_id=service_id,
        days_of_retention=form.get("days_of_retention"),
    )
    if update_count == 0:
        raise InvalidRequest(
            message="The service data retention for id: {} was not found for service: {}".format(data_retention_id, service_id),
            status_code=404,
        )

    return "", 204


@service_blueprint.route("/sensitive-service-ids", methods=["GET"])
def get_sensitive_service_ids():
    data = dao_fetch_service_ids_of_sensitive_services()
    return jsonify(data=data), 200


@service_blueprint.route("/monthly-data-by-service")
def get_monthly_notification_data_by_service():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    result = fact_notification_status_dao.fetch_monthly_notification_statuses_per_service(start_date, end_date)

    return jsonify(result)


def check_unique_name_request_args(request):
    service_id = request.args.get("service_id")
    name = request.args.get("name", None)
    errors = []
    if not service_id:
        errors.append({"service_id": ["Can't be empty"]})
    if not name:
        errors.append({"name": ["Can't be empty"]})
    if errors:
        raise InvalidRequest(errors, status_code=400)
    return service_id, name


def check_unique_email_from_request_args(request):
    service_id = request.args.get("service_id")
    email_from = request.args.get("email_from", None)
    errors = []
    if not service_id:
        errors.append({"service_id": ["Can't be empty"]})
    if not email_from:
        errors.append({"email_from": ["Can't be empty"]})
    if errors:
        raise InvalidRequest(errors, status_code=400)
    return service_id, email_from


def _check_request_args(request):
    service_id = request.args.get("service_id")
    name = request.args.get("name", None)
    email_from = request.args.get("email_from", None)
    errors = []
    if not service_id:
        errors.append({"service_id": ["Can't be empty"]})
    if not name:
        errors.append({"name": ["Can't be empty"]})
    if not email_from:
        errors.append({"email_from": ["Can't be empty"]})
    if errors:
        raise InvalidRequest(errors, status_code=400)
    return service_id, name, email_from


def check_if_reply_to_address_already_in_use(service_id, email_address):
    existing_reply_to_addresses = dao_get_reply_to_by_service_id(service_id)
    if email_address in [i.email_address for i in existing_reply_to_addresses]:
        raise InvalidRequest(
            {
                "0": "Your service already uses ",
                "1": "‘{}’ ".format(email_address),
                "2": "as an email reply-to address.",
            },
            status_code=400,
        )
