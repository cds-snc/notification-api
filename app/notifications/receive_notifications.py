import iso8601
from app import statsd_client
from app.celery.service_callback_tasks import send_inbound_sms_to_service
from app.config import QueueNames
from app.constants import INBOUND_SMS_TYPE, SMS_TYPE
from app.dao.inbound_sms_dao import dao_create_inbound_sms
from app.dao.services_dao import dao_fetch_service_by_inbound_number
from app.errors import register_errors
from app.models import InboundSms, Service
from datetime import datetime
from flask import jsonify, Blueprint, current_app, request, abort
from notifications_utils.recipients import try_validate_and_format_phone_number
from notifications_utils.timezones import convert_local_timezone_to_utc
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse
from typing import Union
from urllib.parse import unquote

receive_notifications_blueprint = Blueprint('receive_notifications', __name__)
register_errors(receive_notifications_blueprint)


@receive_notifications_blueprint.route('/notifications/sms/receive/mmg', methods=['POST'])
def receive_mmg_sms():
    """
    {
        "MSISDN": "447123456789"
        "Number": "40604",
        "Message": "some+uri+encoded+message%3A",
        "ID": "SOME-MMG-SPECIFIC-ID",
        "DateReceived": "2017-05-21+11%3A56%3A11"
    }
    """

    auth = request.authorization

    if auth is None:
        current_app.logger.warning('Inbound sms (MMG) no auth header')
        abort(401)
    elif (
        auth.username not in current_app.config['MMG_INBOUND_SMS_USERNAME']
        or auth.password not in current_app.config['MMG_INBOUND_SMS_AUTH']
    ):
        current_app.logger.warning('Inbound sms (MMG) incorrect username (%s) or password', auth.username)
        abort(403)

    post_data = request.get_json()
    inbound_number = strip_leading_forty_four(post_data['Number'])

    try:
        service = fetch_potential_service(inbound_number, 'mmg')
    except NoSuitableServiceForInboundSms:
        # Since this is an issue with our service <-> number mapping, or no inbound_sms service permission,
        # we should still tell MMG that we received it successfully.
        return 'RECEIVED', 200

    statsd_client.incr('inbound.mmg.successful')

    inbound = create_inbound_sms_object(
        service,
        content=format_mmg_message(post_data['Message']),
        notify_number=inbound_number,
        from_number=post_data['MSISDN'],
        provider_ref=post_data['ID'],
        date_received=format_mmg_datetime(post_data.get('DateReceived')),
        provider_name='mmg',
    )

    send_inbound_sms_to_service.apply_async([str(inbound.id), str(service.id)], queue=QueueNames.NOTIFY)

    current_app.logger.debug(
        '%s received inbound SMS with reference %s from MMG', service.id, inbound.provider_reference
    )
    return jsonify({'status': 'ok'}), 200


@receive_notifications_blueprint.route('/notifications/sms/receive/firetext', methods=['POST'])
def receive_firetext_sms():
    post_data = request.form

    auth = request.authorization
    if not auth:
        current_app.logger.warning('Inbound sms (Firetext) no auth header')
        abort(401)
    elif auth.username != 'notify' or auth.password not in current_app.config['FIRETEXT_INBOUND_SMS_AUTH']:
        current_app.logger.warning('Inbound sms (Firetext) incorrect username (%s) or password', auth.username)
        abort(403)

    inbound_number = strip_leading_forty_four(post_data['destination'])

    try:
        service = fetch_potential_service(inbound_number, 'firetext')
    except NoSuitableServiceForInboundSms:
        return jsonify({'status': 'ok'}), 200

    inbound = create_inbound_sms_object(
        service=service,
        content=post_data['message'],
        notify_number=inbound_number,
        from_number=post_data['source'],
        provider_ref=None,
        date_received=format_mmg_datetime(post_data['time']),
        provider_name='firetext',
    )

    statsd_client.incr('inbound.firetext.successful')

    send_inbound_sms_to_service.apply_async([str(inbound.id), str(service.id)], queue=QueueNames.NOTIFY)
    current_app.logger.debug(
        '%s received inbound SMS with reference %s from Firetext', service.id, inbound.provider_reference
    )
    return jsonify({'status': 'ok'}), 200


@receive_notifications_blueprint.route('/notifications/sms/receive/twilio', methods=['POST'])
def receive_twilio_sms():
    response = MessagingResponse()

    auth = request.authorization

    if not auth:
        current_app.logger.warning('Inbound sms (Twilio) no auth header')
        abort(401)
    elif (
        auth.username not in current_app.config['TWILIO_INBOUND_SMS_USERNAMES']
        or auth.password not in current_app.config['TWILIO_INBOUND_SMS_PASSWORDS']
    ):
        current_app.logger.warning('Inbound sms (Twilio) incorrect username (%s) or password', auth.username)
        abort(403)

    url = request.url
    post_data = request.form
    twilio_signature = request.headers.get('X-Twilio-Signature')

    validator = RequestValidator(current_app.config['TWILIO_AUTH_TOKEN'])

    if not validator.validate(url, post_data, twilio_signature):
        current_app.logger.warning('Inbound sms (Twilio) signature did not match request')
        abort(400)

    try:
        service = fetch_potential_service(post_data['To'], 'twilio')
    except NoSuitableServiceForInboundSms:
        # Since this is an issue with our service <-> number mapping, or no
        # inbound_sms service permission we should still tell Twilio that we
        # received it successfully.
        return str(response), 200

    statsd_client.incr('inbound.twilio.successful')

    inbound = create_inbound_sms_object(
        service,
        content=post_data['Body'],
        notify_number=post_data['To'],
        from_number=post_data['From'],
        provider_ref=post_data['MessageSid'],
        date_received=datetime.utcnow(),
        provider_name='twilio',
    )

    send_inbound_sms_to_service.apply_async([str(inbound.id), str(service.id)], queue=QueueNames.NOTIFY)

    current_app.logger.debug(
        '%s received inbound SMS with reference %s from Twilio', service.id, inbound.provider_reference
    )

    return str(response), 200


def format_mmg_message(message):
    return unescape_string(unquote(message.replace('+', ' ')))


def unescape_string(string):
    return string.encode('raw_unicode_escape').decode('unicode_escape')


def format_mmg_datetime(date):
    """
    We expect datetimes in format 2017-05-21+11%3A56%3A11 - ie, spaces replaced with pluses, and URI encoded
    (the same as UTC)
    """
    orig_date = format_mmg_message(date)
    parsed_datetime = iso8601.parse_date(orig_date).replace(tzinfo=None)
    return convert_local_timezone_to_utc(parsed_datetime)


def create_inbound_sms_object(
    service: Service,
    content: str,
    notify_number: str,
    from_number: str,
    provider_ref: Union[str, None],
    date_received: datetime,
    provider_name: str,
) -> InboundSms:
    user_number = try_validate_and_format_phone_number(
        from_number,
        log_msg=f'Inbound SMS service_id: {service.id} ({service.name}), Invalid from_number received: {from_number}',
    )

    inbound = InboundSms(
        service=service,
        notify_number=notify_number,
        user_number=user_number,
        provider_date=date_received,
        provider_reference=provider_ref,
        content=content,
        provider=provider_name,
    )
    dao_create_inbound_sms(inbound)
    return inbound


class NoSuitableServiceForInboundSms(Exception):
    pass


def fetch_potential_service(
    inbound_number: str,
    provider_name: str,
) -> Service:
    service = dao_fetch_service_by_inbound_number(inbound_number)

    if not service:
        statsd_client.incr(f'inbound.{provider_name}.failed')
        message = f'Inbound number "{inbound_number}" from {provider_name} not associated with a service'
        current_app.logger.error(message)
        raise NoSuitableServiceForInboundSms(message)

    elif not service.has_permissions([INBOUND_SMS_TYPE, SMS_TYPE]):
        statsd_client.incr(f'inbound.{provider_name}.failed')
        message = f'Service "{service.id}" does not allow inbound SMS'
        current_app.logger.error(message)
        raise NoSuitableServiceForInboundSms(message)

    else:
        return service


def strip_leading_forty_four(number):
    if number.startswith('44'):
        return number.replace('44', '0', 1)
    return number
