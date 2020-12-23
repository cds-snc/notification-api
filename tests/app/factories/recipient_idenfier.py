from uuid import uuid4
from app.models import RecipientIdentifier
from app.va.identifier import IdentifierType
import random
import string


def get_random_alphanumeric_string(length=10):
    letters_and_digits = string.ascii_letters + string.digits
    result_str = ''.join((random.choice(letters_and_digits) for i in range(length)))  # nosec
    return result_str


def sample_recipient_identifier(identifier_type=None, notification_id=None):
    if isinstance(identifier_type, IdentifierType):
        id_type = identifier_type.value
    elif identifier_type:
        id_type = identifier_type
    else:
        id_type = random.choice(IdentifierType.values())  # nosec
    id_value = get_random_alphanumeric_string()
    _notification_id = notification_id if notification_id else uuid4()
    return RecipientIdentifier(notification_id=_notification_id,
                               id_type=id_type,
                               id_value=id_value)


def sample_va_profile_identifier(notification_id=None):
    return sample_recipient_identifier(identifier_type=IdentifierType.VA_PROFILE_ID, notification_id=notification_id)
