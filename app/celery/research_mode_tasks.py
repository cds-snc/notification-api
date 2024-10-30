import base64

import random
from datetime import datetime, timedelta
import json

from flask import current_app
from requests import request, RequestException, HTTPError

from notifications_utils.s3 import s3upload

from app import notify_celery
from app.aws.s3 import file_exists
from app.config import QueueNames
from app.constants import SMS_TYPE
from app.celery import process_ses_receipts_tasks, process_pinpoint_receipt_tasks

EMAIL_SIMULATOR_AMAZON_SES_COM = 'success@simulator.amazonses.com'
EMAIL_TEST_NOTIFY_WORKS = 'TEST <TEST@notify.works>'
BOUNCE_EMAIL_AMAZON_SES_COM = 'bounce@simulator.amazonses.com'
LAMBDA_TEST = 'lambda test'

temp_fail = '7700900003'
perm_fail = '7700900002'
delivered = '7700900001'

delivered_email = 'delivered@simulator.notify'
perm_fail_email = 'perm-fail@simulator.notify'
temp_fail_email = 'temp-fail@simulator.notify'


# TODO: Add support for other providers - Twilio / Granicus
def send_sms_response(
    provider,
    notification_id,
    to,
    reference=None,
):
    path = None
    if provider == 'mmg':
        body = mmg_callback(notification_id, to)
        headers = {'Content-type': 'application/json'}
    elif provider == 'twilio':
        body = twilio_callback(notification_id, to)
        headers = {'Content-type': 'application/x-www-form-urlencoded'}
        path = notification_id
    elif provider == 'sns':
        body = sns_callback(reference, to)
        headers = {'Content-type': 'application/json'}
    elif provider == 'pinpoint':
        body = pinpoint_notification_callback_record(reference)
        process_pinpoint_receipt_tasks.process_pinpoint_results.apply_async([body], queue=QueueNames.NOTIFY)
        return
    else:
        headers = {'Content-type': 'application/x-www-form-urlencoded'}
        body = firetext_callback(notification_id, to)
        # to simulate getting a temporary_failure from firetext
        # we need to send a pending status updated then a permanent-failure
        if body['status'] == '2':  # pending status
            make_request(SMS_TYPE, provider, body, headers)
            # 1 is a declined status for firetext, will result in a temp-failure
            body = {'mobile': to, 'status': '1', 'time': '2016-03-10 14:17:00', 'reference': notification_id}

    make_request(SMS_TYPE, provider, body, headers, path)


def send_email_response(
    reference,
    to,
):
    if to == perm_fail_email:
        body = ses_hard_bounce_callback(reference)
    elif to == temp_fail_email:
        body = ses_soft_bounce_callback(reference)
    else:
        body = ses_notification_callback(reference)

    process_ses_receipts_tasks.process_ses_results.apply_async([body], queue=QueueNames.NOTIFY)


def make_request(
    notification_type,
    provider,
    data,
    headers,
    path=None,
):
    callback_url = f"{current_app.config['API_HOST_NAME']}/notifications/{notification_type}/{provider}"
    if path:
        callback_url += f'/{path}'

    try:
        response = request('POST', callback_url, headers=headers, data=data, timeout=60)
        response.raise_for_status()
    except RequestException as e:
        api_error = HTTPError(e)
        current_app.logger.error('API {} request on {} failed with {}'.format('POST', callback_url, api_error.response))
        raise api_error
    finally:
        current_app.logger.info('Mocked provider callback request finished')


def mmg_callback(
    notification_id,
    to,
):
    """
    status: 3 - delivered
    status: 4 - expired (temp failure)
    status: 5 - rejected (perm failure)
    """

    if to.strip().endswith(temp_fail):
        status = '4'
    elif to.strip().endswith(perm_fail):
        status = '5'
    else:
        status = '3'

    return json.dumps(
        {
            'reference': 'mmg_reference',
            'CID': str(notification_id),
            'MSISDN': to,
            'status': status,
            'deliverytime': '2016-04-05 16:01:07',
        }
    )


def firetext_callback(
    notification_id,
    to,
):
    """
    status: 0 - delivered
    status: 1 - perm failure
    """
    if to.strip().endswith(perm_fail):
        status = '1'
    elif to.strip().endswith(temp_fail):
        status = '2'
    else:
        status = '0'
    return {'mobile': to, 'status': status, 'time': '2016-03-10 14:17:00', 'reference': notification_id}


def twilio_callback(
    notification_id,
    to,
):
    if to.strip().endswith(temp_fail):
        status = 'failed'
    elif to.strip().endswith(perm_fail):
        status = 'undelivered'
    else:
        status = 'delivered'

    return {
        'To': to,
        'MessageStatus': status,
        'MessageSid': str(notification_id),
    }


def sns_callback(
    reference,
    to,
):
    from app.notifications.aws_sns_status_callback import SNS_STATUS_FAILURE, SNS_STATUS_SUCCESS

    if to.strip().endswith(temp_fail) or to.strip().endswith(perm_fail):
        status = SNS_STATUS_FAILURE
    else:
        status = SNS_STATUS_SUCCESS

    return json.dumps(
        {
            'notification': {'messageId': reference, 'timestamp': f'{datetime.utcnow()}'},
            'delivery': {
                'phoneCarrier': 'My Phone Carrier',
                'mnc': 270,
                'destination': to,
                'priceInUSD': 0.00645,
                'smsType': 'Transactional',
                'mcc': 310,
                'providerResponse': 'Message has been accepted by phone carrier',
                'dwellTimeMs': 599,
                'dwellTimeMsUntilDeviceAck': 1344,
            },
            'status': status,
        }
    )


def pinpoint_notification_callback_record(
    reference,
    event_type='_SMS.SUCCESS',
    record_status='DELIVERED',
):
    pinpoint_message = {
        'event_type': event_type,
        'event_timestamp': 1553104954322,
        'arrival_timestamp': 1553104954064,
        'event_version': '3.1',
        'application': {'app_id': '123', 'sdk': {}},
        'client': {'client_id': '123456789012'},
        'device': {'platform': {}},
        'session': {},
        'attributes': {
            'sender_request_id': 'e669df09-642b-4168-8563-3e5a4f9dcfbf',
            'campaign_activity_id': '1234',
            'origination_phone_number': '+15555555555',
            'destination_phone_number': '+15555555555',
            'record_status': record_status,
            'iso_country_code': 'US',
            'treatment_id': '0',
            'number_of_message_parts': '1',
            'message_id': reference,
            'message_type': 'Transactional',
            'campaign_id': '12345',
        },
        'metrics': {'price_in_millicents_usd': 645.0},
        'awsAccountId': '123456789012',
    }

    return {'Message': base64.b64encode(bytes(json.dumps(pinpoint_message), 'utf-8')).decode('utf-8')}


@notify_celery.task(bind=True, name='create-fake-letter-response-file', max_retries=5, default_retry_delay=300)
def create_fake_letter_response_file(
    self,
    reference,
):
    now = datetime.utcnow()
    dvla_response_data = '{}|Sent|0|Sorted'.format(reference)

    # try and find a filename that hasn't been taken yet - from a random time within the last 30 seconds
    for i in sorted(range(30), key=lambda _: random.random()):  # nosec
        upload_file_name = 'NOTIFY-{}-RSP.TXT'.format((now - timedelta(seconds=i)).strftime('%Y%m%d%H%M%S'))
        if not file_exists(current_app.config['DVLA_RESPONSE_BUCKET_NAME'], upload_file_name):
            break
    else:
        raise ValueError(
            'cant create fake letter response file for {} - too many files for that time already exist on s3'.format(
                reference
            )
        )

    s3upload(
        filedata=dvla_response_data,
        region=current_app.config['AWS_REGION'],
        bucket_name=current_app.config['DVLA_RESPONSE_BUCKET_NAME'],
        file_location=upload_file_name,
    )
    current_app.logger.info(
        'Fake DVLA response file {}, content [{}], uploaded to {}, created at {}'.format(
            upload_file_name, dvla_response_data, current_app.config['DVLA_RESPONSE_BUCKET_NAME'], now
        )
    )

    # on development we can't trigger SNS callbacks so we need to manually hit the DVLA callback endpoint
    if current_app.config['NOTIFY_ENVIRONMENT'] == 'development':
        make_request('letter', 'dvla', _fake_sns_s3_callback(upload_file_name), None)


def _fake_sns_s3_callback(filename):
    message_contents = '{"Records":[{"s3":{"object":{"key":"%s"}}}]}' % (filename)  # noqa
    return json.dumps({'Type': 'Notification', 'MessageId': 'some-message-id', 'Message': message_contents})


def ses_notification_callback(reference):
    ses_message_body = {
        'delivery': {
            'processingTimeMillis': 2003,
            'recipients': [EMAIL_SIMULATOR_AMAZON_SES_COM],
            'remoteMtaIp': '123.123.123.123',
            'reportingMTA': 'a7-32.smtp-out.eu-west-1.amazonses.com',
            'smtpResponse': '250 2.6.0 Message received',
            'timestamp': '2017-11-17T12:14:03.646Z',
        },
        'mail': {
            'commonHeaders': {
                'from': [EMAIL_TEST_NOTIFY_WORKS],
                'subject': LAMBDA_TEST,
                'to': [EMAIL_SIMULATOR_AMAZON_SES_COM],
            },
            'destination': [EMAIL_SIMULATOR_AMAZON_SES_COM],
            'headers': [
                {'name': 'From', 'value': EMAIL_TEST_NOTIFY_WORKS},
                {'name': 'To', 'value': EMAIL_SIMULATOR_AMAZON_SES_COM},
                {'name': 'Subject', 'value': LAMBDA_TEST},
                {'name': 'MIME-Version', 'value': '1.0'},
                {
                    'name': 'Content-Type',
                    'value': 'multipart/alternative; boundary="----=_Part_617203_1627511946.1510920841645"',
                },
            ],
            'headersTruncated': False,
            'messageId': reference,
            'sendingAccountId': '12341234',
            'source': '"TEST" <TEST@notify.works>',
            'sourceArn': 'arn:aws:ses:eu-west-1:12341234:identity/notify.works',
            'sourceIp': '0.0.0.1',
            'timestamp': '2017-11-17T12:14:01.643Z',
        },
        'eventType': 'Delivery',
    }

    return {
        'Type': 'Notification',
        'MessageId': '8e83c020-1234-1234-1234-92a8ee9baa0a',
        'TopicArn': 'arn:aws:sns:eu-west-1:12341234:ses_notifications',
        'Subject': None,
        'Message': json.dumps(ses_message_body),
        'Timestamp': '2017-11-17T12:14:03.710Z',
        'SignatureVersion': '1',
        'Signature': '[REDACTED]',
        'SigningCertUrl': 'https://sns.eu-west-1.amazonaws.com/SimpleNotificationService-[REDACTED].pem',
        'UnsubscribeUrl': 'https://sns.eu-west-1.amazonaws.com/?Action=Unsubscribe&SubscriptionArn=[REACTED]',
        'MessageAttributes': {},
    }


def ses_hard_bounce_callback(reference):
    return _ses_bounce_callback(reference, 'Permanent')


def ses_soft_bounce_callback(reference):
    return _ses_bounce_callback(reference, 'Temporary')


def _ses_bounce_callback(
    reference,
    bounce_type,
):
    ses_message_body = {
        'bounce': {
            'bounceSubType': 'General',
            'bounceType': bounce_type,
            'bouncedRecipients': [
                {
                    'action': 'failed',
                    'diagnosticCode': 'smtp; 550 5.1.1 user unknown',
                    'emailAddress': BOUNCE_EMAIL_AMAZON_SES_COM,
                    'status': '5.1.1',
                }
            ],
            'feedbackId': '0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000',
            'remoteMtaIp': '123.123.123.123',
            'reportingMTA': 'dsn; a7-31.smtp-out.eu-west-1.amazonses.com',
            'timestamp': '2017-11-17T12:14:05.131Z',
        },
        'mail': {
            'commonHeaders': {
                'from': [EMAIL_TEST_NOTIFY_WORKS],
                'subject': 'ses callback test',
                'to': [BOUNCE_EMAIL_AMAZON_SES_COM],
            },
            'destination': [BOUNCE_EMAIL_AMAZON_SES_COM],
            'headers': [
                {'name': 'From', 'value': EMAIL_TEST_NOTIFY_WORKS},
                {'name': 'To', 'value': BOUNCE_EMAIL_AMAZON_SES_COM},
                {'name': 'Subject', 'value': 'lambda test'},
                {'name': 'MIME-Version', 'value': '1.0'},
                {
                    'name': 'Content-Type',
                    'value': 'multipart/alternative; boundary="----=_Part_596529_2039165601.1510920843367"',
                },
            ],
            'headersTruncated': False,
            'messageId': reference,
            'sendingAccountId': '12341234',
            'source': '"TEST" <TEST@notify.works>',
            'sourceArn': 'arn:aws:ses:eu-west-1:12341234:identity/notify.works',
            'sourceIp': '0.0.0.1',
            'timestamp': '2017-11-17T12:14:03.000Z',
        },
        'eventType': 'Bounce',
    }
    return {
        'Type': 'Notification',
        'MessageId': '36e67c28-1234-1234-1234-2ea0172aa4a7',
        'TopicArn': 'arn:aws:sns:eu-west-1:12341234:ses_notifications',
        'Subject': None,
        'Message': json.dumps(ses_message_body),
        'Timestamp': '2017-11-17T12:14:05.149Z',
        'SignatureVersion': '1',
        'Signature': '[REDACTED]',  # noqa
        'SigningCertUrl': 'https://sns.eu-west-1.amazonaws.com/SimpleNotificationService-[REDACTED]].pem',
        'UnsubscribeUrl': 'https://sns.eu-west-1.amazonaws.com/?Action=Unsubscribe&SubscriptionArn=[REDACTED]]',
        'MessageAttributes': {},
    }
