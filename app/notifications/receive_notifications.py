"""Used to process inbound sms pinpoint responses inside process_pinpoint_inbound_sms"""

from app import statsd_client
from app.constants import INBOUND_SMS_TYPE, SMS_TYPE
from app.dao.inbound_sms_dao import dao_create_inbound_sms
from app.dao.services_dao import dao_fetch_service_by_inbound_number
from app.models import InboundSms, Service
from datetime import datetime
from flask import current_app
from notifications_utils.recipients import try_validate_and_format_phone_number


def create_inbound_sms_object(
    service: Service,
    content: str,
    notify_number: str,
    from_number: str,
    provider_ref: str | None,
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
