import requests
from flask import current_app


def confirm_subscription(confirmation_request):
    url = confirmation_request.get('SubscribeURL')
    if not url:
        current_app.logger.warning('SubscribeURL does not exist or empty')
        return

    try:
        response = requests.get(url, timeout=(3.05, 1))
        response.raise_for_status()
    except requests.RequestException as e:
        current_app.logger.warning('Response: %s', response.text)
        raise e

    return confirmation_request['TopicArn']


def autoconfirm_subscription(req_json):
    if req_json.get('Type') == 'SubscriptionConfirmation':
        current_app.logger.debug('SNS subscription confirmation url: %s', req_json['SubscribeURL'])
        subscribed_topic = confirm_subscription(req_json)
        return subscribed_topic
