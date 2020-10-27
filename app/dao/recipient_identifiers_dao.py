from notifications_utils.statsd_decorators import statsd

from app import db
from app.dao.dao_utils import transactional
from app.models import RecipientIdentifier


@statsd(namespace="dao")
@transactional
def persist_recipient_identifiers(notification_id, form):
    if 'va_identifier' in form:
        va_identifier = form['va_identifier']
        recipient_identifiers = RecipientIdentifier(
            notification_id=notification_id,
            va_identifier_type=va_identifier['id_type'],
            va_identifier_value=va_identifier['value']
        )
        db.session.add(recipient_identifiers)
