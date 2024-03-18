import base64
import pytest
import requests_mock
from app import twilio_sms_client
from app.clients.sms.twilio import get_twilio_responses, TwilioSMSClient
from app.models import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_SENDING,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENT,
)
from tests.app.db import create_service_sms_sender
from twilio.base.exceptions import TwilioRestException
from urllib.parse import parse_qsl


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
    'twilio_status': NOTIFICATION_TECHNICAL_FAILURE,
    'message': 'UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZXN'
    'zYWdlU3RhdHVzPWZhaWxlZCZUbz0lMkIxNzAzMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJ'
    'vbT0lMkIxMzM2NDQzMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDE=',
}


MESSAAGE_BODY_WITH_CANCELED_STATUS = {
    'twilio_status': NOTIFICATION_TECHNICAL_FAILURE,
    'message': 'UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZ'
    'XNzYWdlU3RhdHVzPWNhbmNlbGVkJlRvPSUyQjE3MDMxMTExJk1lc3NhZ2VTaWQ9U015eXkmQWNjb3VudFNpZD1BQ3p6e'
    'iZGcm9tPSUyQjEzMzY0NDMyMjIyJkFwaVZlcnNpb249MjAxMC0wNC0wMQ==',
}


MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30001 = {
    'twilio_status': NOTIFICATION_TECHNICAL_FAILURE,
    'message': 'eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJkVycm'
    '9yQ29kZT0zMDAwMSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZCZUbz0lMk'
    'IxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMjIyMjIyMiZBcGl'
    'WZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=',
}


MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30002 = {
    'twilio_status': NOTIFICATION_PERMANENT_FAILURE,
    'message': 'eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJkV'
    'ycm9yQ29kZT0zMDAwMiZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZCZU'
    'bz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMjIyM'
    'jIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=',
}


MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30003 = {
    'twilio_status': NOTIFICATION_PERMANENT_FAILURE,
    'message': 'eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJ'
    'kVycm9yQ29kZT0zMDAwMyZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZ'
    'CZUbz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyM'
    'jIyMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=',
}


MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30004 = {
    'twilio_status': NOTIFICATION_PERMANENT_FAILURE,
    'message': 'eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJkV'
    'ycm9yQ29kZT0zMDAwNCZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZCZU'
    'bz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMjIyMj'
    'IyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=',
}


MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30005 = {
    'twilio_status': NOTIFICATION_PERMANENT_FAILURE,
    'message': 'eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJ'
    'kVycm9yQ29kZT0zMDAwNSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZC'
    'ZUbz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMjI'
    'yMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=',
}


MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30006 = {
    'twilio_status': NOTIFICATION_PERMANENT_FAILURE,
    'message': 'eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIx'
    'JkVycm9yQ29kZT0zMDAwNiZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWx'
    'lZCZUbz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMj'
    'IyMjIyMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=',
}


MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30007 = {
    'twilio_status': NOTIFICATION_PERMANENT_FAILURE,
    'message': 'eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJk'
    'Vycm9yQ29kZT0zMDAwNyZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZCZ'
    'Ubz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMj'
    'IyMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=',
}


MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30008 = {
    'twilio_status': NOTIFICATION_TECHNICAL_FAILURE,
    'message': 'eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJk'
    'Vycm9yQ29kZT0zMDAwOCZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZ'
    'CZUbz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyM'
    'jIyMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=',
}


MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30009 = {
    'twilio_status': NOTIFICATION_TECHNICAL_FAILURE,
    'message': 'eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJk'
    'Vycm9yQ29kZT0zMDAwOSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZCZ'
    'Ubz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMjI'
    'yMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=',
}


MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30010 = {
    'twilio_status': NOTIFICATION_TECHNICAL_FAILURE,
    'message': 'eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIx'
    'JkVycm9yQ29kZT0zMDAxMCZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWx'
    'lZCZUbz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjI'
    'yMjIyMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=',
}


MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30034 = {
    'twilio_status': NOTIFICATION_PERMANENT_FAILURE,
    'message': 'eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJk'
    'Vycm9yQ29kZT0zMDAzNCZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZCZ'
    'Ubz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMjIy'
    'MjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=',
}


MESSAAGE_BODY_WITH_FAILED_STATUS_AND_INVALID_ERROR_CODE = {
    'twilio_status': NOTIFICATION_TECHNICAL_FAILURE,
    'message': 'eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJ'
    'kVycm9yQ29kZT0zMDAxMSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZ'
    'CZUbz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIy'
    'MjIyMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=',
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
def test_notification_mapping(event, twilio_sms_client_mock):
    translation = twilio_sms_client_mock.translate_delivery_status(event['message'])

    assert 'payload' in translation
    assert 'reference' in translation
    assert 'record_status' in translation
    assert translation['record_status'] == event['twilio_status']


@pytest.mark.parametrize(
    'event',
    [
        MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30001,
        MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30002,
        MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30003,
        MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30004,
        MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30005,
        MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30006,
        MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30007,
        MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30008,
        MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30009,
        MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30010,
        MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30034,
        MESSAAGE_BODY_WITH_FAILED_STATUS_AND_INVALID_ERROR_CODE,
    ],
)
def test_error_code_mapping(event, twilio_sms_client_mock):
    translation = twilio_sms_client_mock.translate_delivery_status(event['message'])

    assert 'payload' in translation
    assert 'reference' in translation
    assert 'record_status' in translation
    assert translation['record_status'] == event['twilio_status']


@pytest.mark.parametrize(
    'event',
    [MESSAAGE_BODY_WITH_ACCEPTED_STATUS, MESSAAGE_BODY_WITH_FAILED_STATUS_AND_ERROR_CODE_30010],
)
def test_returned_payload_is_decoded(event, twilio_sms_client_mock):
    translation = twilio_sms_client_mock.translate_delivery_status(event['message'])

    assert 'payload' in translation
    assert translation['payload'] == base64.b64decode(event['message']).decode()


def test_exception_on_empty_twilio_status_message(twilio_sms_client_mock):
    with pytest.raises(ValueError):
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


def test_should_return_correct_details_for_technical_failure():
    assert get_twilio_responses('failed') == 'technical-failure'


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
