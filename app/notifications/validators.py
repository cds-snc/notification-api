import base64
import binascii

from flask import current_app
from notifications_utils import SMS_CHAR_COUNT_LIMIT
from notifications_utils.recipients import (
    ValidatedPhoneNumber,
    validate_and_format_email_address,
)
from notifications_utils.clients.redis import rate_limit_cache_key, daily_limit_cache_key
from sqlalchemy.orm.exc import NoResultFound

from app import redis_store
from app.constants import (
    INTERNATIONAL_SMS_TYPE,
    SMS_TYPE,
    EMAIL_TYPE,
    KEY_TYPE_TEST,
    KEY_TYPE_TEAM,
    SCHEDULE_NOTIFICATIONS,
)
from app.dao import services_dao, templates_dao
from app.dao.service_sms_sender_dao import dao_get_service_sms_sender_by_id
from app.dao.templates_dao import dao_get_number_of_templates_by_service_id_and_name
from app.feature_flags import is_feature_enabled, FeatureFlag
from app.models import ApiKey, Service
from app.service.utils import service_allowed_to_send_to
from app.v2.errors import TooManyRequestsError, BadRequestError, RateLimitError
from app.notifications.process_notifications import create_content_for_notification
from app.dao.service_letter_contact_dao import dao_get_letter_contact_by_id


def check_service_over_api_rate_limit(
    service: Service,
    api_key: ApiKey,
):
    """Check if the service has exceeded its API rate limit.

    Args:
        service (Service): The service object to check against.
        api_key (ApiKey): The API key object to check against.

    Raises:
        RateLimitError: If the service has exceeded its API rate limit.
    """
    if current_app.config['API_RATE_LIMIT_ENABLED'] and current_app.config['REDIS_ENABLED']:
        cache_key = rate_limit_cache_key(service.id, api_key.key_type)
        rate_limit = service.rate_limit
        interval = 60
        if redis_store.exceeded_rate_limit(cache_key, rate_limit, interval):
            current_app.logger.info('service %s (%s) has been rate limited for throughput', service.id, service.name)
            raise RateLimitError(rate_limit, interval, key_type=api_key.key_type)


def check_service_over_daily_message_limit(
    key_type: str,
    service: Service,
):
    """
    Check if the service has exceeded its daily message limit.
    Log when the service is nearing the limit (>= 75%).
    If the service has exceeded the limit, raise a TooManyRequestsError.

    Args:
        key_type (str): The type of API key used (normal, team, or test).
        service (Service): The service object to check against.

    Raises:
        TooManyRequestsError: If the service has exceeded its daily message limit.
    """
    # Enforce daily message limit only when configured
    # and the service is not using a test key.
    if (
        current_app.config['API_MESSAGE_LIMIT_ENABLED']
        and current_app.config['REDIS_ENABLED']
        and key_type != KEY_TYPE_TEST
    ):
        cache_key = daily_limit_cache_key(service.id)
        service_stats = redis_store.get(cache_key)

        if not service_stats:
            service_stats = services_dao.fetch_todays_total_message_count(service.id)
            redis_store.set(cache_key, service_stats, ex=3600)

        # log if the service has exceeded the limit or is getting close (>= 75%)
        # raise error if the service has exceeded the limit
        if int(service_stats) >= service.message_limit:
            current_app.logger.info(
                'service %s (%s) has been rate limited for daily use sent %s limit %s',
                service.id,
                service.name,
                int(service_stats),
                service.message_limit,
            )
            raise TooManyRequestsError(service.message_limit)

        elif round((int(service_stats) / service.message_limit), 2) * 100 > 75:
            # only log if sent over 75% of the limit, and not already over daily limit
            current_app.logger.info(
                'service %s (%s) nearing daily limit %.1f%% of %s message limit',
                service.id,
                service.name,
                round((int(service_stats) / service.message_limit), 2) * 100,
                service.message_limit,
            )

        # increment the service stats in redis
        if service_stats:
            redis_store.incr(cache_key)


def check_sms_sender_over_rate_limit(
    service_id,
    sms_sender,
):
    if not is_feature_enabled(FeatureFlag.SMS_SENDER_RATE_LIMIT_ENABLED) or sms_sender is None:
        current_app.logger.info('Skipping sms sender rate limit check')
        return

    sms_sender = dao_get_service_sms_sender_by_id(str(service_id), str(sms_sender.id))
    if current_app.config['REDIS_ENABLED']:
        current_app.logger.info('Checking sms sender rate limit')
        cache_key = sms_sender.sms_sender
        rate_limit = sms_sender.rate_limit
        interval = sms_sender.rate_limit_interval
        if redis_store.should_throttle(cache_key, rate_limit, interval):
            current_app.logger.info(f'sms sender {sms_sender.id} has been rate limited for throughput')
            raise RateLimitError(rate_limit, interval)


def check_rate_limiting(
    service,
    api_key,
):
    check_service_over_api_rate_limit(service, api_key)
    check_service_over_daily_message_limit(api_key.key_type, service)


def check_template_is_for_notification_type(
    notification_type,
    template_type,
):
    if notification_type != template_type:
        message = '{0} template is not suitable for {1} notification'.format(template_type, notification_type)
        raise BadRequestError(fields=[{'template': message}], message=message)


def check_template_is_active(template):
    if template.archived:
        raise BadRequestError(fields=[{'template': 'Template has been deleted'}], message='Template has been deleted')


def service_can_send_to_recipient(
    send_to,
    key_type,
    service,
    allow_whitelisted_recipients=True,
):
    if not service_allowed_to_send_to(send_to, service, key_type, allow_whitelisted_recipients):
        if key_type == KEY_TYPE_TEAM:
            message = 'Can’t send to this recipient using a team-only API key'
        else:
            message = (
                'Can’t send to this recipient when service is in trial mode '
                '– see https://www.notifications.service.gov.uk/trial-mode'
            )
        raise BadRequestError(message=message)


# TODO #1410 clean up and remove
def service_has_permission(
    notify_type,
    permissions,
):
    return notify_type in [p.permission for p in permissions]


# TODO #1410 clean up and remove
def check_service_can_schedule_notification(
    permissions,
    scheduled_for,
):
    if scheduled_for:
        if not service_has_permission(SCHEDULE_NOTIFICATIONS, permissions):
            raise BadRequestError(message='Cannot schedule notifications (this feature is invite-only)')


def validate_and_format_recipient(
    send_to,
    key_type,
    service,
    notification_type,
    allow_whitelisted_recipients=True,
):
    if send_to is None:
        raise BadRequestError(message="Recipient can't be empty")

    service_can_send_to_recipient(send_to, key_type, service, allow_whitelisted_recipients)

    if notification_type == SMS_TYPE:
        validated_phone_number = ValidatedPhoneNumber(send_to)

        if validated_phone_number.international and not service.has_permissions(INTERNATIONAL_SMS_TYPE):
            raise BadRequestError(message='Cannot send to international mobile numbers')

        return validated_phone_number.formatted
    elif notification_type == EMAIL_TYPE:
        return validate_and_format_email_address(email_address=send_to)


def validate_template(
    template_id,
    personalisation,
    service,
    notification_type,
):
    try:
        template = templates_dao.dao_get_template_by_id_and_service_id(template_id, service.id)
    except NoResultFound:
        # Putting this in the "message" would be a breaking change for API responses
        current_app.logger.info(
            '%s Validation failure for service: %s (%s) template: %s not found',
            notification_type,
            service.id,
            service.name,
            template_id,
        )
        message = 'Template not found'
        raise BadRequestError(message=message, fields=[{'template': message}])

    check_template_is_for_notification_type(notification_type, template.template_type)
    check_template_is_active(template)
    template_with_content = create_content_for_notification(template, personalisation)

    if template.template_type == SMS_TYPE:
        # We are trying both metric types to see which one works best for us
        current_app.statsd_client.gauge('sms.content_length', template_with_content.content_count)
        # Histogram is a DataDog specific method, which sends a histogram value to statsd.
        current_app.statsd_client.histogram('sms.content_length.histogram', template_with_content.content_count)

    if template.template_type == SMS_TYPE and template_with_content.content_count > SMS_CHAR_COUNT_LIMIT:
        current_app.logger.warning(
            'The personalized message length is %s, which exceeds the 4 segments length of %s.',
            template_with_content.content_count,
            SMS_CHAR_COUNT_LIMIT,
        )
    return template, template_with_content


def get_service_sms_sender_number(
    service_id,
    sms_sender_id,
    notification_type,
):
    if sms_sender_id is not None:
        try:
            return dao_get_service_sms_sender_by_id(str(service_id), str(sms_sender_id)).sms_sender
        except NoResultFound:
            message = f'sms_sender_id {sms_sender_id} does not exist in database for service id {service_id}'
            raise BadRequestError(message=message)


def check_reply_to(
    service_id,
    reply_to_id,
    type_,
):
    if type_ == SMS_TYPE:
        return get_service_sms_sender_number(service_id, reply_to_id, type_)


def check_service_letter_contact_id(
    service_id,
    letter_contact_id,
    notification_type,
):
    if letter_contact_id:
        try:
            return dao_get_letter_contact_by_id(service_id, letter_contact_id).contact_block
        except NoResultFound:
            message = 'letter_contact_id {} does not exist in database for service id {}'.format(
                letter_contact_id, service_id
            )
            raise BadRequestError(message=message)


def decode_personalisation_files(personalisation_data):
    errors = []
    file_keys = [k for k, v in personalisation_data.items() if isinstance(v, dict) and 'file' in v]
    for key in file_keys:
        try:
            personalisation_data[key]['file'] = base64.b64decode(personalisation_data[key]['file'])
        except binascii.Error as e:
            errors.append({'error': 'ValidationError', 'message': f'{key} : {str(e)} : Error decoding base64 field'})
    return personalisation_data, errors


def template_name_already_exists_on_service(
    service_id,
    template_name,
):
    return dao_get_number_of_templates_by_service_id_and_name(service_id, template_name) > 0
