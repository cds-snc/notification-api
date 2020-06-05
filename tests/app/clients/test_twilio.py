import pytest
import requests_mock
from urllib.parse import parse_qsl

from app import twilio_sms_client
from app.clients.sms.twilio import get_twilio_responses
from twilio.base.exceptions import TwilioRestException


def make_twilio_message_response_dict():
    return {
        "account_sid": "TWILIO_TEST_ACCOUNT_SID_XXX",
        "api_version": "2010-04-01",
        "body": "Hello! 👍",
        "date_created": "Thu, 30 Jul 2015 20:12:31 +0000",
        "date_sent": "Thu, 30 Jul 2015 20:12:33 +0000",
        "date_updated": "Thu, 30 Jul 2015 20:12:33 +0000",
        "direction": "outbound-api",
        "error_code": None,
        "error_message": None,
        "from": "+18194120710",
        "messaging_service_sid": "MGXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        "num_media": "0",
        "num_segments": "1",
        "price": -0.00750,
        "price_unit": "USD",
        "sid": "MMXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        "status": "sent",
        "subresource_uris": {
            "media": "/2010-04-01/Accounts/TWILIO_TEST_ACCOUNT_SID_XXX/Messages"
                     "/SMXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX/Media.json"
        },
        "to": "+14155552345",
        "uri": "/2010-04-01/Accounts/TWILIO_TEST_ACCOUNT_SID_XXX/Messages/SMXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX.json",
    }


@pytest.mark.parametrize('status', ['queued', 'sending'])
def test_should_return_correct_details_for_sending(status):
    assert get_twilio_responses(status) == 'sending'


def test_should_return_correct_details_for_sent():
    assert get_twilio_responses('sent') == 'sent'


def test_should_return_correct_details_for_delivery():
    assert get_twilio_responses('delivered') == 'delivered'


def test_should_return_correct_details_for_bounce():
    assert get_twilio_responses('undelivered') == 'permanent-failure'


def test_should_return_correct_details_for_technical_failure():
    assert get_twilio_responses('failed') == 'technical-failure'


def test_should_be_raise_if_unrecognised_status_code():
    with pytest.raises(KeyError) as e:
        get_twilio_responses('unknown_status')
    assert 'unknown_status' in str(e.value)


def test_send_sms_calls_twilio_correctly(notify_api, mocker):
    to = '+61412345678'
    content = 'my message'
    reference = 'my reference'

    response_dict = make_twilio_message_response_dict()

    with requests_mock.Mocker() as request_mock:
        request_mock.post('https://api.twilio.com/2010-04-01/Accounts/TWILIO_TEST_ACCOUNT_SID_XXX/Messages.json',
                          json=response_dict, status_code=200)
        twilio_sms_client.send_sms(to, content, reference)

    assert request_mock.call_count == 1
    req = request_mock.request_history[0]
    assert req.url == 'https://api.twilio.com/2010-04-01/Accounts/TWILIO_TEST_ACCOUNT_SID_XXX/Messages.json'
    assert req.method == 'POST'

    d = dict(parse_qsl(req.text))
    assert d["To"] == "+61412345678"
    assert d["Body"] == "my message"


def test_send_sms_sends_from_hardcoded_number(notify_api, mocker):
    to = '+61412345678'
    content = 'my message'
    reference = 'my reference'

    response_dict = make_twilio_message_response_dict()

    with requests_mock.Mocker() as request_mock:
        request_mock.post('https://api.twilio.com/2010-04-01/Accounts/TWILIO_TEST_ACCOUNT_SID_XXX/Messages.json',
                          json=response_dict, status_code=200)
        twilio_sms_client.send_sms(to, content, reference)

    req = request_mock.request_history[0]

    d = dict(parse_qsl(req.text))
    assert d["From"] == "+18194120710"


def test_send_sms_raises_if_twilio_rejects(notify_api, mocker):
    to = '+61412345678'
    content = 'my message'
    reference = 'my reference'

    response_dict = {
        'code': 60082,
        'message': 'it did not work'
    }

    with pytest.raises(TwilioRestException) as exc, requests_mock.Mocker() as request_mock:
        request_mock.post('https://api.twilio.com/2010-04-01/Accounts/TWILIO_TEST_ACCOUNT_SID_XXX/Messages.json',
                          json=response_dict, status_code=400)
        twilio_sms_client.send_sms(to, content, reference)

    assert exc.value.status == 400
    assert exc.value.code == 60082
    assert exc.value.msg == "Unable to create record: it did not work"


def test_send_sms_raises_if_twilio_fails_to_return_json(notify_api, mocker):
    to = '+61412345678'
    content = 'my message'
    reference = 'my reference'

    response_dict = 'not JSON'

    with pytest.raises(ValueError), requests_mock.Mocker() as request_mock:
        request_mock.post('https://api.twilio.com/2010-04-01/Accounts/TWILIO_TEST_ACCOUNT_SID_XXX/Messages.json',
                          text=response_dict, status_code=200)
        twilio_sms_client.send_sms(to, content, reference)
