from typing import Optional

from sqlalchemy import desc

from app import db
from app.dao.dao_utils import transactional
from app.exceptions import ArchiveValidationError
from app.models import ServiceSmsSender, InboundNumber
from app.service.exceptions import SmsSenderDefaultValidationException, SmsSenderInboundNumberIntegrityException


def insert_service_sms_sender(service, sms_sender):
    """
    This method is called from create_service which is wrapped in a transaction.
    """
    new_sms_sender = ServiceSmsSender(sms_sender=sms_sender,
                                      service=service,
                                      is_default=True
                                      )
    db.session.add(new_sms_sender)


def dao_get_service_sms_sender_by_id(service_id, service_sms_sender_id):
    return ServiceSmsSender.query.filter_by(
        id=service_sms_sender_id,
        service_id=service_id,
        archived=False
    ).one()


def dao_get_sms_senders_by_service_id(service_id):
    return ServiceSmsSender.query.filter_by(
        service_id=service_id,
        archived=False
    ).order_by(desc(ServiceSmsSender.is_default)).all()


def dao_get_sms_sender_by_service_id_and_number(service_id: str, number: str) -> Optional[ServiceSmsSender]:
    return ServiceSmsSender.query.filter_by(
        service_id=service_id,
        sms_sender=number,
        archived=False
    ).first()


@transactional
def dao_add_sms_sender_for_service(service_id, sms_sender, is_default, inbound_number_id=None, rate_limit=None):
    default_sms_sender = _get_default_sms_sender_for_service(service_id=service_id)

    if not default_sms_sender and not is_default:
        raise SmsSenderDefaultValidationException('You must have at least one SMS sender as the default.')

    if is_default:
        _set_default_sms_sender_to_not_default(default_sms_sender)

    if inbound_number_id:
        inbound_number = _allocate_inbound_number_for_service(service_id, inbound_number_id)

        if inbound_number.number != sms_sender:
            raise SmsSenderInboundNumberIntegrityException(
                f"You cannot create an SMS sender with the number '{sms_sender}' "
                f"and the Inbound Number '{inbound_number.id}' ('{inbound_number.number}')"
            )

    new_sms_sender = ServiceSmsSender(
        service_id=service_id,
        sms_sender=sms_sender,
        is_default=is_default,
        inbound_number_id=inbound_number_id,
        rate_limit=rate_limit
    )

    db.session.add(new_sms_sender)
    return new_sms_sender


@transactional
def dao_update_service_sms_sender(service_id, service_sms_sender_id, **kwargs):

    if 'is_default' in kwargs:
        default_sms_sender = _get_default_sms_sender_for_service(service_id)
        is_default = kwargs['is_default']

        if service_sms_sender_id == default_sms_sender.id and not is_default:
            raise SmsSenderDefaultValidationException('You must have at least one SMS sender as the default')

        if is_default:
            _set_default_sms_sender_to_not_default(default_sms_sender)

    if 'inbound_number_id' in kwargs:
        _allocate_inbound_number_for_service(service_id, kwargs['inbound_number_id'])

    sms_sender_to_update = ServiceSmsSender.query.get(service_sms_sender_id)

    if 'sms_sender' in kwargs and sms_sender_to_update.inbound_number_id:
        raise SmsSenderInboundNumberIntegrityException(
            'You cannot update the number for this SMS sender as it has an associated Inbound Number'
        )

    for key, value in kwargs.items():
        setattr(sms_sender_to_update, key, value)

    db.session.add(sms_sender_to_update)
    return sms_sender_to_update


@transactional
def archive_sms_sender(service_id, sms_sender_id):
    sms_sender_to_archive = ServiceSmsSender.query.filter_by(
        id=sms_sender_id,
        service_id=service_id
    ).one()

    if sms_sender_to_archive.inbound_number_id:
        raise ArchiveValidationError("You cannot delete an inbound number")
    if sms_sender_to_archive.is_default:
        raise ArchiveValidationError("You cannot delete a default sms sender")

    sms_sender_to_archive.archived = True

    db.session.add(sms_sender_to_archive)
    return sms_sender_to_archive


def _get_default_sms_sender_for_service(service_id) -> Optional[ServiceSmsSender]:
    sms_senders = dao_get_sms_senders_by_service_id(service_id=service_id)
    if sms_senders:
        old_default = [x for x in sms_senders if x.is_default]
        if len(old_default) == 1:
            return old_default[0]
        else:
            raise SmsSenderDefaultValidationException(
                f"There should only be one default sms sender for each service. "
                f"Service {service_id} has {len(old_default)}"
            )
    return None


def _set_default_sms_sender_to_not_default(existing_default_sms_sender: Optional[ServiceSmsSender]) -> None:
    if existing_default_sms_sender:
        existing_default_sms_sender.is_default = False
        db.session.add(existing_default_sms_sender)


def _allocate_inbound_number_for_service(service_id, inbound_number_id) -> InboundNumber:
    updated = InboundNumber.query.filter_by(
        id=inbound_number_id,
        active=True,
        service_id=None
    ).update(
        {"service_id": service_id}
    )
    if not updated:
        raise SmsSenderInboundNumberIntegrityException(f"Inbound number: {inbound_number_id} is not available")
    return InboundNumber.query.get(inbound_number_id)
