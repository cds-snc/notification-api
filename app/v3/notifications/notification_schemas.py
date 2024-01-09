"""
Define schemas to validate requests to /v3/notifications.
https://json-schema.org/understanding-json-schema/

The ValidationError handler should reference the schemas' "anyOfValidationMessage" attribute, which is not part
of the JSON schema specification, to customize the error message.
"""

from app.models import EMAIL_TYPE, SMS_TYPE
from app.schema_validation.definitions import personalisation
from app.va.identifier import IdentifierType


# This is copied from v2 so v3 does not depend on any v1 or v2 code.  The long
# term goal is to delete older versions.
recipient_identifier_schema = {
    '$schema': 'http://json-schema.org/draft/2020-12/schema',
    'type': 'object',
    'properties': {'id_type': {'type': 'string', 'enum': IdentifierType.values()}, 'id_value': {'type': 'string'}},
    'required': ['id_type', 'id_value'],
}


# All notification types include these properties.  They should be added to notification-type-specific schemas.
common_properties = {
    'billing_code': {'type': 'string', 'maxLength': 256},
    'client_reference': {'type': 'string'},
    'personalisation': personalisation,
    'recipient_identifier': recipient_identifier_schema,
    'reference': {'type': 'string'},
    'scheduled_for': {'type': 'string', 'format': 'date-time'},
    'template_id': {'type': 'string', 'format': 'uuid'},
}


notification_v3_post_email_request_schema = {
    '$schema': 'http://json-schema.org/draft/2020-12/schema',
    'type': 'object',
    'properties': {
        'email_address': {'type': 'string', 'format': 'email'},
        'email_reply_to_id': {'type': 'string', 'format': 'uuid'},
        'notification_type': {'const': EMAIL_TYPE},
    },
    'additionalProperties': False,
    'required': ['notification_type', 'template_id'],
    'anyOf': [{'required': ['email_address']}, {'required': ['recipient_identifier']}],
    'anyOfValidationMessage': 'You must provide an e-mail address or recipient identifier.',
}
notification_v3_post_email_request_schema['properties'].update(common_properties)


notification_v3_post_sms_request_schema = {
    '$schema': 'http://json-schema.org/draft/2020-12/schema',
    'type': 'object',
    'properties': {
        'notification_type': {'const': SMS_TYPE},
        # Note that there is no "phone_number" string format, contrary to the v2 schema definition.
        'phone_number': {'type': 'string'},
        'sms_sender_id': {'type': 'string', 'format': 'uuid'},
    },
    'additionalProperties': False,
    'required': ['notification_type', 'template_id'],
    'anyOf': [{'required': ['phone_number']}, {'required': ['recipient_identifier']}],
    'anyOfValidationMessage': 'You must provide a phone number or recipient identifier.',
}
notification_v3_post_sms_request_schema['properties'].update(common_properties)
