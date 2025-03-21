from flask import Blueprint, current_app, jsonify, request
from marshmallow import ValidationError
from notifications_utils import SMS_CHAR_COUNT_LIMIT
from notifications_utils.recipients import get_international_phone_info

from app import api_user, authenticated_service
from app.dao import notifications_dao, templates_dao
from app.errors import InvalidRequest, register_errors
from app.models import (
    EMAIL_TYPE,
    INTERNATIONAL_SMS_TYPE,
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    LETTER_TYPE,
    SMS_TYPE,
    NotificationType,
    Template,
)
from app.notifications.process_notifications import (
    persist_notification,
    send_notification_to_queue,
    simulated_recipient,
)
from app.notifications.validators import (
    check_email_annual_limit,
    check_email_daily_limit,
    check_rate_limiting,
    check_sms_annual_limit,
    check_template_is_active,
    check_template_is_for_notification_type,
    service_has_permission,
)
from app.schemas import (
    email_notification_schema,
    notification_with_personalisation_schema,
    notifications_filter_schema,
    sms_template_notification_schema,
)
from app.service.utils import service_allowed_to_send_to
from app.utils import (
    get_delivery_queue_for_template,
    get_document_url,
    get_public_notify_type_text,
    get_template_instance,
    pagination_links,
)

notifications = Blueprint("notifications", __name__)

register_errors(notifications)


@notifications.route("/notifications/<uuid:notification_id>", methods=["GET"])
def get_notification_by_id(notification_id):
    notification = notifications_dao.get_notification_with_personalisation(
        str(authenticated_service.id), notification_id, key_type=None
    )
    if notification is not None:
        return jsonify(data={"notification": notification_with_personalisation_schema.dump(notification)}), 200
    else:
        return jsonify(result="error", message="Notification not found in database"), 404


@notifications.route("/notifications", methods=["GET"])
def get_all_notifications():
    data = notifications_filter_schema.load(request.args)
    include_jobs = data.get("include_jobs", False)
    page = data.get("page", 1)
    page_size = data.get("page_size", current_app.config.get("API_PAGE_SIZE"))
    limit_days = data.get("limit_days")

    pagination = notifications_dao.get_notifications_for_service(
        str(authenticated_service.id),
        personalisation=True,
        filter_dict=data,
        page=page,
        page_size=page_size,
        limit_days=limit_days,
        key_type=api_user.key_type,
        include_jobs=include_jobs,
    )
    return (
        jsonify(
            notifications=notification_with_personalisation_schema.dump(pagination.items, many=True),
            page_size=page_size,
            total=pagination.total,
            links=pagination_links(pagination, ".get_all_notifications", **request.args.to_dict()),
        ),
        200,
    )


@notifications.route("/notifications/<string:notification_type>", methods=["POST"])
def send_notification(notification_type: NotificationType):
    if notification_type not in [SMS_TYPE, EMAIL_TYPE]:
        msg = "{} notification type is not supported".format(notification_type)
        msg = msg + ", please use the latest version of the client" if notification_type == LETTER_TYPE else msg
        raise InvalidRequest(msg, 400)

    try:
        notification_form = (  # type: ignore
            sms_template_notification_schema if notification_type == SMS_TYPE else email_notification_schema
        ).load(request.get_json())
    except ValidationError as err:
        errors = err.messages
        raise InvalidRequest(errors, status_code=400)

    current_app.logger.info(f"POST to V1 API: send_notification, service_id: {authenticated_service.id}")

    check_rate_limiting(authenticated_service, api_user)

    template = templates_dao.dao_get_template_by_id_and_service_id(
        template_id=notification_form["template"], service_id=authenticated_service.id
    )

    simulated = simulated_recipient(notification_form["to"], notification_type)
    if not simulated != api_user.key_type == KEY_TYPE_TEST and notification_type == EMAIL_TYPE:
        check_email_annual_limit(authenticated_service, 1)
        check_email_daily_limit(authenticated_service, 1)

    check_template_is_for_notification_type(notification_type, template.template_type)
    check_template_is_active(template)

    template_object = create_template_object_for_notification(template, notification_form.get("personalisation", {}))

    _service_allowed_to_send_to(notification_form, authenticated_service)
    if not service_has_permission(notification_type, authenticated_service.permissions):
        raise InvalidRequest(
            {"service": ["Cannot send {}".format(get_public_notify_type_text(notification_type, plural=True))]},
            status_code=400,
        )

    if notification_type == SMS_TYPE:
        _service_can_send_internationally(authenticated_service, notification_form["to"])
        if not simulated and api_user.key_type != KEY_TYPE_TEST:
            check_sms_annual_limit(authenticated_service, 1)
    # Do not persist or send notification to the queue if it is a simulated recipient

    notification_model = persist_notification(
        template_id=template.id,
        template_version=template.version,
        template_postage=template.postage,
        recipient=request.get_json()["to"],  # type: ignore
        service=authenticated_service,
        personalisation=notification_form.get("personalisation", None),
        notification_type=notification_type,
        api_key_id=api_user.id,
        key_type=api_user.key_type,
        simulated=simulated,
        reply_to_text=template.get_reply_to_text(),
    )
    if not simulated:
        send_notification_to_queue(
            notification=notification_model,
            research_mode=authenticated_service.research_mode,
            queue=get_delivery_queue_for_template(template),
        )
    else:
        current_app.logger.debug("POST simulated notification for id: {}".format(notification_model.id))
    notification_form.update({"template_version": template.version})

    return (
        jsonify(data=get_notification_return_data(notification_model.id, notification_form, template_object)),
        201,
    )


def get_notification_return_data(notification_id, notification, template):
    output = {
        "body": str(template),
        "template_version": notification["template_version"],
        "notification": {"id": notification_id},
    }

    if template.template_type == "email":
        output.update({"subject": template.subject})

    return output


def _service_can_send_internationally(service, number):
    international_phone_info = get_international_phone_info(number)

    if international_phone_info.international and INTERNATIONAL_SMS_TYPE not in [p.permission for p in service.permissions]:
        raise InvalidRequest({"to": ["Cannot send to international mobile numbers"]}, status_code=400)


def _service_allowed_to_send_to(notification, service):
    if not service_allowed_to_send_to(notification["to"], service, api_user.key_type):
        # FIXME: hard code it for now until we can get en/fr specific links and text
        if api_user.key_type == KEY_TYPE_TEAM:
            message = (
                f"Can’t send to this recipient using a team-only API key (service {service.id}) "
                f'- see {get_document_url("en", "keys.html#team-and-safelist")}'
            )
        else:
            message = (
                "Can’t send to this recipient when service is in trial mode " f'– see {get_document_url("en", "keys.html#live")}'
            )
        raise InvalidRequest({"to": [message]}, status_code=400)


def create_template_object_for_notification(template, personalisation) -> Template:
    template_object = get_template_instance(template.__dict__, personalisation)

    if template_object.missing_data:
        message = "Missing personalisation: {}".format(", ".join(template_object.missing_data))
        errors = {"template": [message]}
        raise InvalidRequest(errors, status_code=400)

    if template_object.template_type == SMS_TYPE and template_object.content_count > SMS_CHAR_COUNT_LIMIT:
        message = "Content has a character count greater than the limit of {}".format(SMS_CHAR_COUNT_LIMIT)
        errors = {"content": [message]}
        raise InvalidRequest(errors, status_code=400)
    return template_object
