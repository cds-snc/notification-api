import base64
from datetime import datetime
from uuid import uuid4

import pytest
import requests_mock
from twilio.base.exceptions import TwilioRestException
from urllib.parse import parse_qsl

from app import twilio_sms_client
from app.celery.exceptions import NonRetryableException
from app.clients.sms import SmsStatusRecord
from app.clients.sms.twilio import get_twilio_responses, TwilioSMSClient, TwilioStatus
from app.constants import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_SENDING,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENT,
)
from app.exceptions import InvalidProviderException
from lambda_functions.vetext_incoming_forwarder_lambda.twilio_signature_utils import generate_twilio_signature_and_body
from tests.app.db import create_service_sms_sender


FAKE_DELIVERY_STATUS_URI = 'https://api.va.gov/sms/deliverystatus'
FAKE_DELIVERY_STATUS_TOKEN = 'unit_test'


class FakeClient:
    def __init__(self, **kwargs):
        self.messages = self.MessageFactory()

    class MessageFactory:
        def __call__(self, *args, **kwds):
            return self

        @staticmethod
        def fetch(**kwargs):
            raise TwilioRestException(status=kwargs.get('status', 0), uri=kwargs.get('uri', 'https://www.va.gov'))


class MockSmsSenderObject:
    sms_sender = ''
    sms_sender_specifics = {}


def build_callback_url(expected_prefix, client):
    test_url = (
        f'https://{expected_prefix}api.va.gov/vanotify/sms/deliverystatus'
        f'#ct={client._callback_connection_timeout}'
        f'&rc={client._callback_retry_count}'
        f'&rt={client._callback_read_timeout}'
        f'&rp={client._callback_retry_policy}'
    )
    return test_url


def make_twilio_message_response_dict():
    return {
        'account_sid': 'TWILIO_TEST_ACCOUNT_SID_XXX',
        'api_version': '2010-04-01',
        'body': 'Hello! 👍',
        'date_created': 'Thu, 30 Jul 2015 20:12:31 +0000',
        'date_sent': 'Thu, 30 Jul 2015 20:12:33 +0000',
        'date_updated': 'Thu, 30 Jul 2015 20:12:33 +0000',
        'direction': 'outbound-api',
        'error_code': None,
        'error_message': None,
        'from': '+18194120710',
        'messaging_service_sid': 'MGXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX',
        'num_media': '0',
        'num_segments': '1',
        'price': -0.00750,
        'price_unit': 'USD',
        'sid': 'MMXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX',
        'status': 'sent',
        'subresource_uris': {
            'media': '/2010-04-01/Accounts/TWILIO_TEST_ACCOUNT_SID_XXX/Messages'
            '/SMXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX/Media.json'
        },
        'to': '+14155552345',
        'uri': '/2010-04-01/Accounts/TWILIO_TEST_ACCOUNT_SID_XXX/Messages/SMXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX.json',
    }


# First parameter is the environment value passed to the task definition
# second parameter is the prefix for the reverse proxy endpoint for that
# environment
ENV_LIST = [
    ('staging', 'staging-'),
    ('performance', 'sandbox-'),
    ('production', ''),
    ('development', 'dev-'),
]


class ServiceSmsSender:
    def __init__(self, message_service_id):
        self.sms_sender = 'Test Sender'
        self.sms_sender_specifics = {'messaging_service_sid': message_service_id}


@pytest.fixture
def service_sms_sender(request):
    return ServiceSmsSender(request.param)


MESSAAGE_BODY_WITH_ACCEPTED_STATUS = {
    'twilio_status': NOTIFICATION_SENDING,
    'message': 'UmF3RmxvYXRJbmRlckRhdG09MjMwMzA5MjAyMSZTbXNTaWQ9UzJlNzAyOGMwZTBhNmYzZjY0YWM3N2E4YWY0OWVkZmY3JlNtc1N0Y'
    'XR1cz1hY2NlcHRlZCZNZXNzYWdlU3RhdHVzPWFjY2VwdGVkJlRvPSUyQjE3MDM5MzI3OTY5Jk1lc3NhZ2VTaWQ9UzJlNzAyOGMwZTB'
    'hNmYzZjY0YWM3N2E4YWY0OWVkZmY3JkFjY291bnRTaWQ9QUMzNTIxNjg0NTBjM2EwOGM5ZTFiMWQ2OGM1NDc4ZGZmYw==',
}


MESSAAGE_BODY_WITH_SCHEDULED_STATUS = {
    'twilio_status': NOTIFICATION_SENDING,
    'message': 'UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZXNzYWdlU3RhdHVzPXNja'
    'GVkdWxlZCZUbz0lMkIxNzAzMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMzM2NDQzMjIyMiZB'
    'cGlWZXJzaW9uPTIwMTAtMDQtMDE=',
}


MESSAAGE_BODY_WITH_QUEUED_STATUS = {
    'twilio_status': NOTIFICATION_SENDING,
    'message': 'UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZXNzYWdlU3RhdHVzPXF1Z'
    'XVlZCZUbz0lMkIxNzAzMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMzM2NDQzMjIyMiZBcG'
    'lWZXJzaW9uPTIwMTAtMDQtMDE=',
}


MESSAAGE_BODY_WITH_SENDING_STATUS = {
    'twilio_status': NOTIFICATION_SENDING,
    'message': 'UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZXNzYWdlU3RhdHVz'
    'PXNlbmRpbmcmVG89JTJCMTcwMzExMTEmTWVzc2FnZVNpZD1TTXl5eSZBY2NvdW50U2lkPUFDenp6JkZyb209JTJCMTMzNjQ0MzIyMjImQX'
    'BpVmVyc2lvbj0yMDEwLTA0LTAx',
}


MESSAAGE_BODY_WITH_SENT_STATUS = {
    'twilio_status': NOTIFICATION_SENT,
    'message': 'UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZXNzYWdlU3R'
    'hdHVzPXNlbnQmVG89JTJCMTcwMzExMTEmTWVzc2FnZVNpZD1TTXl5eSZBY2NvdW50U2lkPUFDenp6JkZyb209JTJCMTMzNjQ0MzIyM'
    'jImQXBpVmVyc2lvbj0yMDEwLTA0LTAx',
}


MESSAAGE_BODY_WITH_DELIVERED_STATUS = {
    'twilio_status': NOTIFICATION_DELIVERED,
    'message': 'UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZXNzYW'
    'dlU3RhdHVzPWRlbGl2ZXJlZCZUbz0lMkIxNzAzMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT'
    '0lMkIxMzM2NDQzMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDE=',
}


MESSAAGE_BODY_WITH_UNDELIVERED_STATUS = {
    'twilio_status': NOTIFICATION_PERMANENT_FAILURE,
    'message': 'UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZX'
    'NzYWdlU3RhdHVzPXVuZGVsaXZlcmVkJlRvPSUyQjE3MDMxMTExJk1lc3NhZ2VTaWQ9U015eXkmQWNjb3VudFNpZD1BQ3'
    'p6eiZGcm9tPSUyQjEzMzY0NDMyMjIyJkFwaVZlcnNpb249MjAxMC0wNC0wMQ==',
}


MESSAAGE_BODY_WITH_FAILED_STATUS = {
    'twilio_status': NOTIFICATION_PERMANENT_FAILURE,
    'message': 'UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZXN'
    'zYWdlU3RhdHVzPWZhaWxlZCZUbz0lMkIxNzAzMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJ'
    'vbT0lMkIxMzM2NDQzMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDE=',
}


MESSAAGE_BODY_WITH_CANCELED_STATUS = {
    'twilio_status': NOTIFICATION_PERMANENT_FAILURE,
    'message': 'UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZ'
    'XNzYWdlU3RhdHVzPWNhbmNlbGVkJlRvPSUyQjE3MDMxMTExJk1lc3NhZ2VTaWQ9U015eXkmQWNjb3VudFNpZD1BQ3p6e'
    'iZGcm9tPSUyQjEzMzY0NDMyMjIyJkFwaVZlcnNpb249MjAxMC0wNC0wMQ==',
}


MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30010 = {
    'twilio_status': NOTIFICATION_PERMANENT_FAILURE,
    'message': 'eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIx'
    'JkVycm9yQ29kZT0zMDAxMCZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWx'
    'lZCZUbz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjI'
    'yMjIyMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=',
}


MESSAGE_BODY_WITH_NO_MESSAGE_STATUS = {
    'twilio_status': None,
    'message': 'eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDky'
    'MDIxJkVycm9yQ29kZT0zMDAxMSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZUbz0lMkIxMTExMTEx'
    'MTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMjIyMjIyMiZBcGlWZX'
    'JzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=',
}


MESSAGE_BODY_WITH_INVALID_MESSAGE_STATUS = {
    'twilio_status': None,
    'message': 'eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDI'
    'xJkVycm9yQ29kZT0zMDAxMSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWlud'
    'mFsaWQmVG89JTJCMTExMTExMTExMTEmTWVzc2FnZVNpZD1TTXl5eSZBY2NvdW50U2lkPUFDenp6JkZyb209JT'
    'JCMTIyMjIyMjIyMjImQXBpVmVyc2lvbj0yMDEwLTA0LTAxIiwgInByb3ZpZGVyIjogInR3aWxpbyJ9fV19',
}


@pytest.fixture
def sample_twilio_delivery_status():
    """Take a TwilioStatus mapping and generate a body and signature to match."""

    def _wrapper(twilio_status: TwilioStatus):
        return generate_twilio_signature_and_body(
            token=FAKE_DELIVERY_STATUS_TOKEN,
            uri=FAKE_DELIVERY_STATUS_URI,
            error_code=str(twilio_status.code),
            message_status='failed',
        )

    yield _wrapper


@pytest.fixture
def twilio_sms_client_mock(mocker):
    client = TwilioSMSClient('CREDS', 'CREDS')

    logger = mocker.Mock()

    client.init_app(logger, '', '')

    return client


@pytest.mark.parametrize(
    'event',
    [
        MESSAAGE_BODY_WITH_ACCEPTED_STATUS,
        MESSAAGE_BODY_WITH_SCHEDULED_STATUS,
        MESSAAGE_BODY_WITH_QUEUED_STATUS,
        MESSAAGE_BODY_WITH_SENDING_STATUS,
        MESSAAGE_BODY_WITH_SENT_STATUS,
        MESSAAGE_BODY_WITH_DELIVERED_STATUS,
        MESSAAGE_BODY_WITH_UNDELIVERED_STATUS,
        MESSAAGE_BODY_WITH_FAILED_STATUS,
        MESSAAGE_BODY_WITH_CANCELED_STATUS,
    ],
)
def test_notification_price_mapping(event, twilio_sms_client_mock):
    translation: SmsStatusRecord = twilio_sms_client_mock.translate_delivery_status(event['message'])

    assert translation.price_millicents == 0.0


@pytest.mark.parametrize(
    'event',
    [
        MESSAAGE_BODY_WITH_ACCEPTED_STATUS,
        MESSAAGE_BODY_WITH_SCHEDULED_STATUS,
        MESSAAGE_BODY_WITH_QUEUED_STATUS,
        MESSAAGE_BODY_WITH_SENDING_STATUS,
        MESSAAGE_BODY_WITH_SENT_STATUS,
        MESSAAGE_BODY_WITH_DELIVERED_STATUS,
        MESSAAGE_BODY_WITH_UNDELIVERED_STATUS,
        MESSAAGE_BODY_WITH_FAILED_STATUS,
        MESSAAGE_BODY_WITH_CANCELED_STATUS,
    ],
)
def test_notification_parts_mapping(event, twilio_sms_client_mock):
    translation: SmsStatusRecord = twilio_sms_client_mock.translate_delivery_status(event['message'])

    assert translation.message_parts == 1


@pytest.mark.parametrize(
    'event',
    [
        MESSAAGE_BODY_WITH_ACCEPTED_STATUS,
        MESSAAGE_BODY_WITH_SCHEDULED_STATUS,
        MESSAAGE_BODY_WITH_QUEUED_STATUS,
        MESSAAGE_BODY_WITH_SENDING_STATUS,
        MESSAAGE_BODY_WITH_SENT_STATUS,
        MESSAAGE_BODY_WITH_DELIVERED_STATUS,
        MESSAAGE_BODY_WITH_UNDELIVERED_STATUS,
        MESSAAGE_BODY_WITH_FAILED_STATUS,
        MESSAAGE_BODY_WITH_CANCELED_STATUS,
    ],
)
def test_notification_mapping(event, twilio_sms_client_mock):
    translation: SmsStatusRecord = twilio_sms_client_mock.translate_delivery_status(event['message'])

    assert translation.status == event['twilio_status']

    if translation.status not in (NOTIFICATION_PERMANENT_FAILURE):
        assert translation.status_reason is None
    else:
        assert translation.status_reason is not None


@pytest.mark.parametrize(
    'twilio_status',
    [
        *TwilioSMSClient.twilio_error_code_map.values(),
        TwilioStatus(-1, NOTIFICATION_PERMANENT_FAILURE, 'Technical error'),
    ],
    ids=[*TwilioSMSClient.twilio_error_code_map.keys(), 'invalid-error-code'],
)
def test_delivery_status_error_code_mapping(
    twilio_status: TwilioStatus, twilio_sms_client_mock, sample_twilio_delivery_status
):
    _, msg = sample_twilio_delivery_status(twilio_status)
    translation: SmsStatusRecord = twilio_sms_client_mock.translate_delivery_status(msg)

    assert translation.status == twilio_status.status
    assert translation.status_reason is not None


@pytest.mark.parametrize(
    'event',
    [MESSAAGE_BODY_WITH_ACCEPTED_STATUS, MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30010],
)
def test_returned_payload_is_decoded(event, twilio_sms_client_mock):
    translation: SmsStatusRecord = twilio_sms_client_mock.translate_delivery_status(event['message'])

    assert translation.payload == base64.b64decode(event['message']).decode()


def test_exception_on_empty_twilio_status_message(twilio_sms_client_mock):
    with pytest.raises(NonRetryableException):
        twilio_sms_client_mock.translate_delivery_status(None)


def test_exception_on_missing_twilio_message_status(twilio_sms_client_mock):
    with pytest.raises(KeyError):
        twilio_sms_client_mock.translate_delivery_status(MESSAGE_BODY_WITH_NO_MESSAGE_STATUS['message'])


def test_exception_on_invalid_twilio_status(twilio_sms_client_mock):
    with pytest.raises(ValueError):
        twilio_sms_client_mock.translate_delivery_status(MESSAGE_BODY_WITH_INVALID_MESSAGE_STATUS['message'])


@pytest.mark.parametrize('status', ['queued', 'sending'])
def test_should_return_correct_details_for_sending(status):
    assert get_twilio_responses(status) == 'sending'


def test_should_return_correct_details_for_sent():
    assert get_twilio_responses('sent') == 'sent'


def test_should_return_correct_details_for_delivery():
    assert get_twilio_responses('delivered') == 'delivered'


def test_should_return_correct_details_for_bounce():
    assert get_twilio_responses('undelivered') == 'permanent-failure'


def test_should_return_correct_details_for_permanent_failure():
    assert get_twilio_responses('failed') == 'permanent-failure'


def test_should_be_raise_if_unrecognised_status_code():
    with pytest.raises(KeyError) as e:
        get_twilio_responses('unknown_status')
    assert 'unknown_status' in str(e.value)


def test_send_sms_calls_twilio_correctly(
    notify_api,
):
    to = '+61412345678'
    content = 'my message'
    url = f'https://api.twilio.com/2010-04-01/Accounts/{twilio_sms_client._account_sid}/Messages.json'

    with requests_mock.Mocker() as r_mock:
        r_mock.post(url, json=make_twilio_message_response_dict(), status_code=200)
        twilio_sms_client.send_sms(to, content, 'my reference')

    assert r_mock.call_count == 1
    req = r_mock.request_history[0]
    assert req.url == url
    assert req.method == 'POST'

    d = dict(parse_qsl(req.text))
    assert d['To'] == to
    assert d['Body'] == content


@pytest.mark.parametrize('sms_sender_id', ['test_sender_id', None], ids=['has sender id', 'no sender id'])
def test_send_sms_call_with_sender_id_and_specifics(
    notify_db_session,
    sample_service,
    notify_api,
    mocker,
    sms_sender_id,
):
    to = '+61412345678'
    content = 'my message'
    reference = 'my reference'
    sms_sender_specifics_info = {'messaging_service_sid': 'test-service-sid-123'}

    create_service_sms_sender(
        service=sample_service(),
        sms_sender='test_sender',
        is_default=False,
        sms_sender_specifics=sms_sender_specifics_info,
    )

    response_dict = make_twilio_message_response_dict()
    sms_sender_with_specifics = MockSmsSenderObject()
    sms_sender_with_specifics.sms_sender_specifics = sms_sender_specifics_info
    sms_sender_with_specifics.sms_sender = '+18194120710'
    url = f'https://api.twilio.com/2010-04-01/Accounts/{twilio_sms_client._account_sid}/Messages.json'

    with requests_mock.Mocker() as r_mock:
        r_mock.post(
            url,
            json=response_dict,
            status_code=200,
        )

        if sms_sender_id is not None:
            mocker.patch(
                'app.dao.service_sms_sender_dao.dao_get_service_sms_sender_by_id',
                return_value=sms_sender_with_specifics,
            )
        else:
            mocker.patch(
                'app.dao.service_sms_sender_dao.dao_get_service_sms_sender_by_service_id_and_number',
                return_value=sms_sender_with_specifics,
            )

        twilio_sid = twilio_sms_client.send_sms(
            to, content, reference, service_id='test_service_id', sender='test_sender', sms_sender_id=sms_sender_id
        )

    assert response_dict['sid'] == twilio_sid

    assert r_mock.call_count == 1
    req = r_mock.request_history[0]
    assert req.url == url
    assert req.method == 'POST'

    d = dict(parse_qsl(req.text))

    assert d['To'] == to
    assert d['Body'] == content
    assert d['MessagingServiceSid'] == sms_sender_specifics_info['messaging_service_sid']
    # sample_service will clean up the created ServiceSmsSender


def test_send_sms_sends_from_hardcoded_number(
    notify_api,
    mocker,
):
    to = '+61412345678'
    content = 'my message'
    reference = 'my reference'

    response_dict = make_twilio_message_response_dict()

    sms_sender_mock = MockSmsSenderObject()
    sms_sender_mock.sms_sender = '+18194120710'

    with requests_mock.Mocker() as r_mock:
        r_mock.post(
            f'https://api.twilio.com/2010-04-01/Accounts/{twilio_sms_client._account_sid}/Messages.json',
            json=response_dict,
            status_code=200,
        )

        mocker.patch(
            'app.dao.service_sms_sender_dao.dao_get_service_sms_sender_by_service_id_and_number',
            return_value=sms_sender_mock,
        )

        twilio_sms_client.send_sms(to, content, reference)

    req = r_mock.request_history[0]

    d = dict(parse_qsl(req.text))
    assert d['From'] == '+18194120710'


def test_send_sms_raises_if_twilio_rejects(
    notify_api,
    mocker,
):
    to = '+61412345678'
    content = 'my message'
    reference = 'my reference'
    response_dict = {'code': 60082, 'message': 'it did not work'}

    with pytest.raises(TwilioRestException) as exc:
        with requests_mock.Mocker() as r_mock:
            r_mock.post(
                f'https://api.twilio.com/2010-04-01/Accounts/{twilio_sms_client._account_sid}/Messages.json',
                json=response_dict,
                status_code=400,
            )

            twilio_sms_client.send_sms(to, content, reference)

    assert exc.value.status == 400
    assert exc.value.code == 60082
    assert exc.value.msg == 'Unable to create record: it did not work'


def test_send_sms_raises_if_twilio_fails_to_return_json(
    notify_api,
    mocker,
):
    to = '+61412345678'
    content = 'my message'
    reference = 'my reference'
    response_dict = 'not JSON'

    with pytest.raises(ValueError):
        with requests_mock.Mocker() as r_mock:
            r_mock.post(
                f'https://api.twilio.com/2010-04-01/Accounts/{twilio_sms_client._account_sid}/Messages.json',
                text=response_dict,
                status_code=200,
            )

            twilio_sms_client.send_sms(to, content, reference)


@pytest.mark.parametrize('environment, expected_prefix', ENV_LIST)
def test_send_sms_twilio_callback_url(environment, expected_prefix):
    client = TwilioSMSClient('creds', 'creds')

    # Test with environment set to "staging"
    client.init_app(None, None, environment)
    test_url = build_callback_url(expected_prefix, client)

    assert client.callback_url == test_url


@pytest.mark.parametrize('environment, expected_prefix', ENV_LIST)
@pytest.mark.parametrize('service_sms_sender', ['message-service-id', None], indirect=True)
def test_send_sms_twilio_callback(
    mocker,
    service_sms_sender,
    environment,
    expected_prefix,
):
    account_sid = 'test_account_sid'
    auth_token = 'test_auth_token'
    to = '+1234567890'
    content = 'Test message'
    reference = 'test_reference'
    callback_notify_url_host = 'https://api.va.gov'
    logger = mocker.Mock()

    twilio_sms_client = TwilioSMSClient(account_sid, auth_token)
    twilio_sms_client.init_app(logger, callback_notify_url_host, environment)
    expected_callback_url = build_callback_url(expected_prefix, twilio_sms_client)

    response_dict = {
        'sid': 'test_sid',
        'to': to,
        'from': service_sms_sender.sms_sender,
        'body': content,
        'status': 'sent',
        'status_callback': expected_callback_url,
    }

    with requests_mock.Mocker() as r_mock:
        r_mock.post(
            f'https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json',
            json=response_dict,
            status_code=200,
        )

        # Patch the relevant DAO functions
        mocker.patch(
            'app.dao.service_sms_sender_dao.dao_get_service_sms_sender_by_service_id_and_number',
            return_value=service_sms_sender,
        )

        twilio_sid = twilio_sms_client.send_sms(
            to,
            content,
            reference,
            service_id='test_service_id',
            sender='test_sender',
        )

        req = r_mock.request_history[0]
        d = dict(parse_qsl(req.text))

        # Assert the correct callback URL is used in the request
        expected_callback_url = build_callback_url(expected_prefix, twilio_sms_client)
        assert d['StatusCallback'] == expected_callback_url

        # Assert the expected Twilio SID is returned
        assert response_dict['sid'] == twilio_sid


@pytest.mark.parametrize(
    (
        'response_dict',
        'exception',
    ),
    (
        (
            {
                'code': 21606,
                'message': "The 'From' phone number provided (+61412345678) is not a valid message-capable Twilio phone number for this destination",
            },
            InvalidProviderException,
        ),
        (
            {
                'code': 21617,
                'message': 'Unable to create record: The concatenated message body exceeds the 1600 character limit',
            },
            NonRetryableException,
        ),
    ),
    ids=(
        'invalid-from-number',
        'message-too-long',
    ),
)
def test_send_sms_raises_non_retryable_exception_with_invalid_request(
    notify_api,
    mocker,
    response_dict,
    exception,
):
    to = '+61412345678'
    content = 'my message'
    reference = 'my reference'

    with pytest.raises(exception):
        with requests_mock.Mocker() as r_mock:
            r_mock.post(
                f'https://api.twilio.com/2010-04-01/Accounts/{twilio_sms_client._account_sid}/Messages.json',
                json=response_dict,
                status_code=400,
            )

            twilio_sms_client.send_sms(to, content, reference)


def test_get_twilio_message(
    notify_api,
    mocker,
):
    twilio_sid = 'test_sid'
    response_dict = make_twilio_message_response_dict()
    response_dict['sid'] = twilio_sid

    with requests_mock.Mocker() as r_mock:
        r_mock.get(
            f'https://api.twilio.com/2010-04-01/Accounts/{twilio_sms_client._account_sid}/Messages/{twilio_sid}.json',
            json=response_dict,
            status_code=200,
        )

        response = twilio_sms_client.get_twilio_message(twilio_sid)

    assert response.sid == twilio_sid
    assert response.status == 'sent'


def test_update_notification_status_override(
    notify_api,
    mocker,
    sample_notification,
    notify_db_session,
):
    response_dict = make_twilio_message_response_dict()
    response_dict['sid'] = 'test_sid'
    response_dict['status'] = 'delivered'
    twilio_sid = response_dict['sid']

    notification = sample_notification(status='sending', reference=twilio_sid)

    with requests_mock.Mocker() as r_mock:
        r_mock.get(
            f'https://api.twilio.com/2010-04-01/Accounts/{twilio_sms_client._account_sid}/Messages/{twilio_sid}.json',
            json=response_dict,
            status_code=200,
        )

        twilio_sms_client.update_notification_status_override(twilio_sid)

    # Retrieve the updated notification
    notify_db_session.session.refresh(notification)
    assert notification.status == 'delivered'


def test_update_notification_with_unknown_sid(
    notify_api,
    mocker,
):
    twilio_sid = f'{str(uuid4())}-twilio-sid'
    twilio_sms_client._client = FakeClient()

    mock_logger = mocker.spy(twilio_sms_client.logger, 'exception')
    twilio_sms_client.update_notification_status_override(twilio_sid)
    mock_logger.assert_called_once_with('Twilio message not found: %s', twilio_sid)


def test_translate_raw_dlr_done_date():
    raw_dlr_done_date = '2410281326'
    print(datetime.strptime(raw_dlr_done_date, TwilioSMSClient.RAW_DLR_DONE_DATE_FMT))
    assert twilio_sms_client._translate_raw_dlr_done_date(raw_dlr_done_date) == datetime(2024, 10, 28, 13, 26)


def test_translate_raw_dlr_done_date_to_long(mocker):
    # Extra 2 at the end
    raw_dlr_done_date = '24102813222'
    assert twilio_sms_client._translate_raw_dlr_done_date(raw_dlr_done_date) != datetime(2024, 10, 28, 13, 22)
