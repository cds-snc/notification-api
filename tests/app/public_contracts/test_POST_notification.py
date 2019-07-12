from flask import json

from . import return_json_from_response, validate_v0
from tests import create_authorization_header


def _post_notification(client, template, url, to):
    data = {
        'to': to,
        'template': str(template.id)
    }

    auth_header = create_authorization_header(service_id=template.service_id)

    return client.post(
        path=url,
        data=json.dumps(data),
        headers=[('Content-Type', 'application/json'), auth_header]
    )


def test_post_sms_contract(client, mocker, sample_template):
    mocker.patch('app.celery.provider_tasks.deliver_sms.apply_async')

    response_json = return_json_from_response(_post_notification(
        client, sample_template, url='/notifications/sms', to='6502532222'
    ))
    validate_v0(response_json, 'POST_notification_return_sms.json')


def test_post_email_contract(client, mocker, sample_email_template):
    mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    response_json = return_json_from_response(_post_notification(
        client, sample_email_template, url='/notifications/email', to='foo@bar.com'
    ))
    validate_v0(response_json, 'POST_notification_return_email.json')
