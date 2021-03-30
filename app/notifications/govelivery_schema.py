from app.clients.email.govdelivery_client import govdelivery_status_map

govdelivery_webhook_schema = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "x-www-form-urlencoded POST from Granicus with delivery status define at https://developer.govdelivery.com/api/tms/resource/webhooks/",  # noqa: E501
    "type": "object",
    "title": "POST data for /notifications/govdelivery",
    "properties": {
        "sid": {"type": "string"},
        "message_url": {"type": "string", "format": "uri"},
        "recipient_url": {"type": "string", "format": "uri"},
        "status": {"enum": govdelivery_status_map.keys()},
        "message_type": {"enum": ["sms", "email"]},
        "completed_at": {"type": "string"},
        "error_message": {"type": "string"}
    },
    "required": ["message_url", "status", "sid", "message_type"]
}
