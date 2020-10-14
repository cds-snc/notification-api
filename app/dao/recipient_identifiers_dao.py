from notifications_utils.statsd_decorators import statsd

from app import db
from app.dao.dao_utils import transactional
from app.models import RecipientIdentifiers


@statsd(namespace="dao")
@transactional
def persist_recipient_identifiers(notification_id, va_identifier_type, va_identifier_value):
    recipient_identifiers = RecipientIdentifiers(
        notification_id=notification_id,
        va_identifier_type=va_identifier_type,
        va_identifier_value=va_identifier_value
    )
    db.session.add(recipient_identifiers)
    db.session.commit()
