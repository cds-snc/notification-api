from flask import json
from tests import create_authorization_header


def post_send_notification(client, service, notification_type, payload):
    return client.post(
        path=f'/v2/notifications/{notification_type}',
        data=json.dumps(payload),
        headers=[('Content-Type', 'application/json'), create_authorization_header(service_id=service.id)],
    )
