import pytest
from app.models import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_SENDING,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENT,
)
from app.clients.sms.twilio import TwilioSMSClient

message_body_with_accepted_status = {
    "twilio_status": NOTIFICATION_SENDING,
    "message": "UmF3RmxvYXRJbmRlckRhdG09MjMwMzA5MjAyMSZTbXNTaWQ9UzJlNzAyOGMwZTBhNmYzZjY0YWM3N2E4YWY0OWVkZmY3JlNtc1N0Y"
    "XR1cz1hY2NlcHRlZCZNZXNzYWdlU3RhdHVzPWFjY2VwdGVkJlRvPSUyQjE3MDM5MzI3OTY5Jk1lc3NhZ2VTaWQ9UzJlNzAyOGMwZTB"
    "hNmYzZjY0YWM3N2E4YWY0OWVkZmY3JkFjY291bnRTaWQ9QUMzNTIxNjg0NTBjM2EwOGM5ZTFiMWQ2OGM1NDc4ZGZmYw==",
}

message_body_with_scheduled_status = {
    "twilio_status": NOTIFICATION_SENDING,
    "message": "UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZXNzYWdlU3RhdHVzPXNja"
    "GVkdWxlZCZUbz0lMkIxNzAzMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMzM2NDQzMjIyMiZB"
    "cGlWZXJzaW9uPTIwMTAtMDQtMDE=",
}


message_body_with_queued_status = {
    "twilio_status": NOTIFICATION_SENDING,
    "message": "UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZXNzYWdlU3RhdHVzPXF1Z"
    "XVlZCZUbz0lMkIxNzAzMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMzM2NDQzMjIyMiZBcG"
    "lWZXJzaW9uPTIwMTAtMDQtMDE=",
}


message_body_with_sending_status = {
    "twilio_status": NOTIFICATION_SENDING,
    "message": "UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZXNzYWdlU3RhdHVz"
    "PXNlbmRpbmcmVG89JTJCMTcwMzExMTEmTWVzc2FnZVNpZD1TTXl5eSZBY2NvdW50U2lkPUFDenp6JkZyb209JTJCMTMzNjQ0MzIyMjImQX"
    "BpVmVyc2lvbj0yMDEwLTA0LTAx",
}


message_body_with_sent_status = {
    "twilio_status": NOTIFICATION_SENT,
    "message": "UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZXNzYWdlU3R"
    "hdHVzPXNlbnQmVG89JTJCMTcwMzExMTEmTWVzc2FnZVNpZD1TTXl5eSZBY2NvdW50U2lkPUFDenp6JkZyb209JTJCMTMzNjQ0MzIyM"
    "jImQXBpVmVyc2lvbj0yMDEwLTA0LTAx",
}


message_body_with_delivered_status = {
    "twilio_status": NOTIFICATION_DELIVERED,
    "message": "UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZXNzYW"
    "dlU3RhdHVzPWRlbGl2ZXJlZCZUbz0lMkIxNzAzMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT"
    "0lMkIxMzM2NDQzMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDE=",
}


message_body_with_undelivered_status = {
    "twilio_status": NOTIFICATION_PERMANENT_FAILURE,
    "message": "UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZX"
    "NzYWdlU3RhdHVzPXVuZGVsaXZlcmVkJlRvPSUyQjE3MDMxMTExJk1lc3NhZ2VTaWQ9U015eXkmQWNjb3VudFNpZD1BQ3"
    "p6eiZGcm9tPSUyQjEzMzY0NDMyMjIyJkFwaVZlcnNpb249MjAxMC0wNC0wMQ==",
}


message_body_with_failed_status = {
    "twilio_status": NOTIFICATION_TECHNICAL_FAILURE,
    "message": "UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZXN"
    "zYWdlU3RhdHVzPWZhaWxlZCZUbz0lMkIxNzAzMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJ"
    "vbT0lMkIxMzM2NDQzMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDE=",
}


message_body_with_canceled_status = {
    "twilio_status": NOTIFICATION_TECHNICAL_FAILURE,
    "message": "UmF3RGxyRG9uZURhdGU9MjMwMzA3MjE1NSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWRlbGl2ZXJlZCZNZ"
    "XNzYWdlU3RhdHVzPWNhbmNlbGVkJlRvPSUyQjE3MDMxMTExJk1lc3NhZ2VTaWQ9U015eXkmQWNjb3VudFNpZD1BQ3p6e"
    "iZGcm9tPSUyQjEzMzY0NDMyMjIyJkFwaVZlcnNpb249MjAxMC0wNC0wMQ==",
}

message_body_with_failed_status_and_error_code_30001 = {
    "twilio_status": NOTIFICATION_TECHNICAL_FAILURE,
    "message": "eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJkVycm"
    "9yQ29kZT0zMDAwMSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZCZUbz0lMk"
    "IxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMjIyMjIyMiZBcGl"
    "WZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=",
}

message_body_with_failed_status_and_error_code_30002 = {
    "twilio_status": NOTIFICATION_PERMANENT_FAILURE,
    "message": "eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJkV"
    "ycm9yQ29kZT0zMDAwMiZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZCZU"
    "bz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMjIyM"
    "jIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=",
}

message_body_with_failed_status_and_error_code_30003 = {
    "twilio_status": NOTIFICATION_PERMANENT_FAILURE,
    "message": "eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJ"
    "kVycm9yQ29kZT0zMDAwMyZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZ"
    "CZUbz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyM"
    "jIyMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=",
}

message_body_with_failed_status_and_error_code_30004 = {
    "twilio_status": NOTIFICATION_PERMANENT_FAILURE,
    "message": "eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJkV"
    "ycm9yQ29kZT0zMDAwNCZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZCZU"
    "bz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMjIyMj"
    "IyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=",
}

message_body_with_failed_status_and_error_code_30005 = {
    "twilio_status": NOTIFICATION_PERMANENT_FAILURE,
    "message": "eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJ"
    "kVycm9yQ29kZT0zMDAwNSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZC"
    "ZUbz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMjI"
    "yMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=",
}

message_body_with_failed_status_and_error_code_30006 = {
    "twilio_status": NOTIFICATION_PERMANENT_FAILURE,
    "message": "eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIx"
    "JkVycm9yQ29kZT0zMDAwNiZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWx"
    "lZCZUbz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMj"
    "IyMjIyMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=",
}

message_body_with_failed_status_and_error_code_30007 = {
    "twilio_status": NOTIFICATION_PERMANENT_FAILURE,
    "message": "eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJk"
    "Vycm9yQ29kZT0zMDAwNyZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZCZ"
    "Ubz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMj"
    "IyMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=",
}

message_body_with_failed_status_and_error_code_30008 = {
    "twilio_status": NOTIFICATION_TECHNICAL_FAILURE,
    "message": "eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJk"
    "Vycm9yQ29kZT0zMDAwOCZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZ"
    "CZUbz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyM"
    "jIyMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=",
}

message_body_with_failed_status_and_error_code_30009 = {
    "twilio_status": NOTIFICATION_TECHNICAL_FAILURE,
    "message": "eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJk"
    "Vycm9yQ29kZT0zMDAwOSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZCZ"
    "Ubz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMjI"
    "yMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=",
}

message_body_with_failed_status_and_error_code_30010 = {
    "twilio_status": NOTIFICATION_TECHNICAL_FAILURE,
    "message": "eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIx"
    "JkVycm9yQ29kZT0zMDAxMCZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWx"
    "lZCZUbz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjI"
    "yMjIyMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=",
}

message_body_with_failed_status_and_invalid_error_code = {
    "twilio_status": NOTIFICATION_TECHNICAL_FAILURE,
    "message": "eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDIxJ"
    "kVycm9yQ29kZT0zMDAxMSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWZhaWxlZ"
    "CZUbz0lMkIxMTExMTExMTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIy"
    "MjIyMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=",
}

message_body_with_no_message_status = {
    "twilio_status": None,
    "message": "eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDky"
    "MDIxJkVycm9yQ29kZT0zMDAxMSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZUbz0lMkIxMTExMTEx"
    "MTExMSZNZXNzYWdlU2lkPVNNeXl5JkFjY291bnRTaWQ9QUN6enomRnJvbT0lMkIxMjIyMjIyMjIyMiZBcGlWZX"
    "JzaW9uPTIwMTAtMDQtMDEiLCAicHJvdmlkZXIiOiAidHdpbGlvIn19XX0=",
}

message_body_with_invalid_message_status = {
    "twilio_status": None,
    "message": "eyJhcmdzIjogW3siTWVzc2FnZSI6IHsiYm9keSI6ICJSYXdEbHJEb25lRGF0ZT0yMzAzMDkyMDI"
    "xJkVycm9yQ29kZT0zMDAxMSZTbXNTaWQ9U014eHgmU21zU3RhdHVzPWZhaWxlZCZNZXNzYWdlU3RhdHVzPWlud"
    "mFsaWQmVG89JTJCMTExMTExMTExMTEmTWVzc2FnZVNpZD1TTXl5eSZBY2NvdW50U2lkPUFDenp6JkZyb209JT"
    "JCMTIyMjIyMjIyMjImQXBpVmVyc2lvbj0yMDEwLTA0LTAxIiwgInByb3ZpZGVyIjogInR3aWxpbyJ9fV19",
}


@pytest.fixture
def twilio_sms_client(mocker):
    client = TwilioSMSClient("CREDS", "CREDS")

    logger = mocker.Mock()

    client.init_app(logger, "")

    return client


@pytest.mark.parametrize(
    "event",
    [
        (message_body_with_accepted_status),
        (message_body_with_scheduled_status),
        (message_body_with_queued_status),
        (message_body_with_sending_status),
        (message_body_with_sent_status),
        (message_body_with_delivered_status),
        (message_body_with_undelivered_status),
        (message_body_with_failed_status),
        (message_body_with_canceled_status),
    ],
)
def test_notification_mapping(event, twilio_sms_client):
    translation = twilio_sms_client.translate_delivery_status(event["message"])

    assert "payload" in translation
    assert "reference" in translation
    assert "record_status" in translation
    assert translation["record_status"] == event["twilio_status"]


@pytest.mark.parametrize(
    "event",
    [
        (message_body_with_failed_status_and_error_code_30001),
        (message_body_with_failed_status_and_error_code_30002),
        (message_body_with_failed_status_and_error_code_30003),
        (message_body_with_failed_status_and_error_code_30004),
        (message_body_with_failed_status_and_error_code_30005),
        (message_body_with_failed_status_and_error_code_30006),
        (message_body_with_failed_status_and_error_code_30007),
        (message_body_with_failed_status_and_error_code_30008),
        (message_body_with_failed_status_and_error_code_30009),
        (message_body_with_failed_status_and_error_code_30010),
        (message_body_with_failed_status_and_invalid_error_code),
    ],
)
def test_error_code_mapping(event, twilio_sms_client):
    translation = twilio_sms_client.translate_delivery_status(event["message"])

    assert "payload" in translation
    assert "reference" in translation
    assert "record_status" in translation
    assert translation["record_status"] == event["twilio_status"]


def test_exception_on_empty_twilio_status_message(twilio_sms_client):
    with pytest.raises(ValueError):
        twilio_sms_client.translate_delivery_status(None)


def test_exception_on_missing_twilio_message_status(twilio_sms_client):
    with pytest.raises(KeyError):
        twilio_sms_client.translate_delivery_status(
            message_body_with_no_message_status["message"]
        )


def test_exception_on_invalid_twilio_status(twilio_sms_client):
    with pytest.raises(ValueError):
        twilio_sms_client.translate_delivery_status(
            message_body_with_invalid_message_status["message"]
        )
