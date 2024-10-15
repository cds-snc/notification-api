import json


def sns_s3_callback(filename, message_id="some-message-id"):
    message_contents = '{"Records":[{"s3":{"object":{"key":"%s"}}}]}' % (filename)  # noqa
    return json.dumps(
        {
            "Type": "Notification",
            "MessageId": message_id,
            "Message": message_contents,
        }
    )


def ses_notification_callback(reference):
    ses_message_body = {
        "delivery": {
            "processingTimeMillis": 2003,
            "recipients": ["success@simulator.amazonses.com"],
            "remoteMtaIp": "123.123.123.123",
            "reportingMTA": "a7-32.smtp-out.eu-west-1.amazonses.com",
            "smtpResponse": "250 2.6.0 Message received",
            "timestamp": "2017-11-17T12:14:03.646Z",
        },
        "mail": {
            "commonHeaders": {
                "from": ["TEST <TEST@notify.works>"],
                "subject": "lambda test",
                "to": ["success@simulator.amazonses.com"],
            },
            "destination": ["success@simulator.amazonses.com"],
            "headers": [
                {"name": "From", "value": "TEST <TEST@notify.works>"},
                {"name": "To", "value": "success@simulator.amazonses.com"},
                {"name": "Subject", "value": "lambda test"},
                {"name": "MIME-Version", "value": "1.0"},
                {
                    "name": "Content-Type",
                    "value": 'multipart/alternative; boundary="----=_Part_617203_1627511946.1510920841645"',
                },
            ],
            "headersTruncated": False,
            "messageId": reference,
            "sendingAccountId": "12341234",
            "source": '"TEST" <TEST@notify.works>',
            "sourceArn": "arn:aws:ses:eu-west-1:12341234:identity/notify.works",
            "sourceIp": "0.0.0.1",
            "timestamp": "2017-11-17T12:14:01.643Z",
        },
        "notificationType": "Delivery",
    }

    return {
        "Type": "Notification",
        "MessageId": "8e83c020-1234-1234-1234-92a8ee9baa0a",
        "TopicArn": "arn:aws:sns:eu-west-1:12341234:ses_notifications",
        "Subject": None,
        "Message": json.dumps(ses_message_body),
        "Timestamp": "2017-11-17T12:14:03.710Z",
        "SignatureVersion": "1",
        "Signature": "[REDACTED]",
        "SigningCertUrl": "https://sns.eu-west-1.amazonaws.com/SimpleNotificationService-[REDACTED].pem",
        "UnsubscribeUrl": "https://sns.eu-west-1.amazonaws.com/?Action=Unsubscribe&SubscriptionArn=[REACTED]",
        "MessageAttributes": {},
    }


def ses_hard_bounce_callback(reference, bounce_subtype=None):
    return _ses_bounce_callback(reference, "Permanent", bounce_subtype)


def ses_soft_bounce_callback(reference, bounce_subtype=None):
    return _ses_bounce_callback(reference, "Transient", bounce_subtype)


def ses_complaint_callback_malformed_message_id():
    return {
        "Signature": "bb",
        "SignatureVersion": "1",
        "MessageAttributes": {},
        "MessageId": "98c6e927-af5d-5f3b-9522-bab736f2cbde",
        "UnsubscribeUrl": "https://sns.eu-west-1.amazonaws.com",
        "TopicArn": "arn:ses_notifications",
        "Type": "Notification",
        "Timestamp": "2018-06-05T14:00:15.952Z",
        "Subject": None,
        "Message": '{"notificationType":"Complaint","complaint":{"complainedRecipients":[{"emailAddress":"recipient1@example.com"}],"timestamp":"2018-06-05T13:59:58.000Z","feedbackId":"ses_feedback_id"},"mail":{"timestamp":"2018-06-05T14:00:15.950Z","source":"\\"Some Service\\" <someservicenotifications.service.gov.uk>","sourceArn":"arn:identity/notifications.service.gov.uk","sourceIp":"52.208.24.161","sendingAccountId":"888450439860","badMessageId":"ref1","destination":["recipient1@example.com"]}}',  # noqa
        "SigningCertUrl": "https://sns.pem",
    }


def ses_complaint_callback_with_missing_complaint_type():
    """
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/notification-contents.html#complaint-object
    """
    return {
        "Signature": "bb",
        "SignatureVersion": "1",
        "MessageAttributes": {},
        "MessageId": "98c6e927-af5d-5f3b-9522-bab736f2cbde",
        "UnsubscribeUrl": "https://sns.eu-west-1.amazonaws.com",
        "TopicArn": "arn:ses_notifications",
        "Type": "Notification",
        "Timestamp": "2018-06-05T14:00:15.952Z",
        "Subject": None,
        "Message": '{"notificationType":"Complaint","complaint":{"complainedRecipients":[{"emailAddress":"recipient1@example.com"}],"timestamp":"2018-06-05T13:59:58.000Z","feedbackId":"ses_feedback_id"},"mail":{"timestamp":"2018-06-05T14:00:15.950Z","source":"\\"Some Service\\" <someservicenotifications.service.gov.uk>","sourceArn":"arn:identity/notifications.service.gov.uk","sourceIp":"52.208.24.161","sendingAccountId":"888450439860","messageId":"ref1","destination":["recipient1@example.com"]}}',  # noqa
        "SigningCertUrl": "https://sns.pem",
    }


def ses_complaint_callback():
    """
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/notification-contents.html#complaint-object
    """
    return {
        "Signature": "bb",
        "SignatureVersion": "1",
        "MessageAttributes": {},
        "MessageId": "98c6e927-af5d-5f3b-9522-bab736f2cbde",
        "UnsubscribeUrl": "https://sns.eu-west-1.amazonaws.com",
        "TopicArn": "arn:ses_notifications",
        "Type": "Notification",
        "Timestamp": "2018-06-05T14:00:15.952Z",
        "Subject": None,
        "Message": '{"notificationType":"Complaint","complaint":{"complaintFeedbackType": "abuse", "complainedRecipients":[{"emailAddress":"recipient1@example.com"}],"timestamp":"2018-06-05T13:59:58.000Z","feedbackId":"ses_feedback_id"},"mail":{"timestamp":"2018-06-05T14:00:15.950Z","source":"\\"Some Service\\" <someservicenotifications.service.gov.uk>","sourceArn":"arn:identity/notifications.service.gov.uk","sourceIp":"52.208.24.161","sendingAccountId":"888450439860","messageId":"ref1","destination":["recipient1@example.com"]}}',  # noqa
        "SigningCertUrl": "https://sns.pem",
    }


def ses_complaint_callback_with_subtype(subtype):
    """
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/notification-contents.html#complaint-object
    """
    return {
        "Signature": "bb",
        "SignatureVersion": "1",
        "MessageAttributes": {},
        "MessageId": "98c6e927-af5d-5f3b-9522-bab736f2cbde",
        "UnsubscribeUrl": "https://sns.eu-west-1.amazonaws.com",
        "TopicArn": "arn:ses_notifications",
        "Type": "Notification",
        "Timestamp": "2018-06-05T14:00:15.952Z",
        "Subject": None,
        "Message": '{"notificationType":"Complaint","complaint":{"complaintFeedbackType": "abuse", "complainedRecipients":[{"emailAddress":"recipient1@example.com"}],"timestamp":"2018-06-05T13:59:58.000Z","feedbackId":"ses_feedback_id", "complaintSubType":"'
        + subtype
        + '"},"mail":{"timestamp":"2018-06-05T14:00:15.950Z","source":"\\"Some Service\\" <someservicenotifications.service.gov.uk>","sourceArn":"arn:identity/notifications.service.gov.uk","sourceIp":"52.208.24.161","sendingAccountId":"888450439860","messageId":"ref1","destination":["recipient1@example.com"]}}',  # noqa
        "SigningCertUrl": "https://sns.pem",
    }


def sns_success_callback(reference=None, timestamp="2016-06-28 00:40:34.558", destination="+1XXX5550100"):
    # Payload details: https://docs.aws.amazon.com/sns/latest/dg/sms_stats_cloudwatch.html
    body = {
        "notification": {"messageId": reference, "timestamp": timestamp},
        "delivery": {
            "phoneCarrier": "My Phone Carrier",
            "mnc": 270,
            "destination": destination,
            "priceInUSD": 0.00645,
            "smsType": "Transactional",
            "mcc": 310,
            "providerResponse": "Message has been accepted by phone carrier",
            "dwellTimeMs": 599,
            "dwellTimeMsUntilDeviceAck": 1344,
        },
        "status": "SUCCESS",
    }

    return _sns_callback(body)


def sns_failed_callback(provider_response, reference=None, timestamp="2016-06-28 00:40:34.558", destination="+1XXX5550100"):
    # Payload details: https://docs.aws.amazon.com/sns/latest/dg/sms_stats_cloudwatch.html
    body = {
        "notification": {
            "messageId": reference,
            "timestamp": timestamp,
        },
        "delivery": {
            "mnc": 0,
            "destination": destination,
            "priceInUSD": 0.00645,
            "smsType": "Transactional",
            "mcc": 0,
            "providerResponse": provider_response,
            "dwellTimeMs": 1420,
            "dwellTimeMsUntilDeviceAck": 1692,
        },
        "status": "FAILURE",
    }

    return _sns_callback(body)


# Note that 1467074434 = 2016-06-28 00:40:34.558 UTC
def pinpoint_successful_callback(reference=None, timestamp=1467074434, destination="+1XXX5550100"):
    body = {
        "eventType": "TEXT_SUCCESSFUL",
        "eventVersion": "1.0",
        "eventTimestamp": timestamp,
        "isFinal": False,
        "originationPhoneNumber": "+13655550100",
        "destinationPhoneNumber": destination,
        "isoCountryCode": "CA",
        "mcc": "302",
        "mnc": "610",
        "carrierName": "Bell Cellular Inc. / Aliant Telecom",
        "messageId": reference,
        "messageRequestTimestamp": timestamp,
        "messageEncoding": "GSM",
        "messageType": "TRANSACTIONAL",
        "messageStatus": "SUCCESSFUL",
        "messageStatusDescription": "Message has been accepted by phone carrier",
        "totalMessageParts": 1,
        "totalMessagePrice": 0.00581,
        "totalCarrierFee": 0.00767,
    }

    return _pinpoint_callback(body)


def pinpoint_delivered_callback(reference=None, timestamp=1467074434, destination="+1XXX5550100"):
    body = {
        "eventType": "TEXT_DELIVERED",
        "eventVersion": "1.0",
        "eventTimestamp": timestamp,
        "isFinal": True,
        "originationPhoneNumber": "+13655550100",
        "destinationPhoneNumber": destination,
        "isoCountryCode": "CA",
        "mcc": "302",
        "mnc": "610",
        "carrierName": "Bell Cellular Inc. / Aliant Telecom",
        "messageId": reference,
        "messageRequestTimestamp": timestamp,
        "messageEncoding": "GSM",
        "messageType": "TRANSACTIONAL",
        "messageStatus": "DELIVERED",
        "messageStatusDescription": "Message has been accepted by phone",
        "totalMessageParts": 1,
        "totalMessagePrice": 0.00581,
        "totalCarrierFee": 0.006,
    }

    return _pinpoint_callback(body)


def pinpoint_shortcode_delivered_callback(reference=None, timestamp=1467074434, destination="+1XXX5550100"):
    body = {
        "eventType": "TEXT_SUCCESSFUL",
        "eventVersion": "1.0",
        "eventTimestamp": timestamp,
        "isFinal": True,
        "originationPhoneNumber": "555555",
        "destinationPhoneNumber": destination,
        "isoCountryCode": "CA",
        "messageId": reference,
        "messageRequestTimestamp": timestamp,
        "messageEncoding": "GSM",
        "messageType": "TRANSACTIONAL",
        "messageStatus": "SUCCESSFUL",
        "messageStatusDescription": "Message has been accepted by phone carrier",
        "totalMessageParts": 1,
        "totalMessagePrice": 0.00581,
        "totalCarrierFee": 0.006,
    }

    return _pinpoint_callback(body)


# Note that 1467074434 = 2016-06-28 00:40:34.558 UTC
def pinpoint_failed_callback(provider_response, reference=None, timestamp=1467074434, destination="+1XXX5550100"):
    body = {
        "eventType": "TEXT_CARRIER_UNREACHABLE",
        "eventVersion": "1.0",
        "eventTimestamp": timestamp,
        "isFinal": True,
        "originationPhoneNumber": "+13655550100",
        "destinationPhoneNumber": destination,
        "isoCountryCode": "CA",
        "messageId": reference,
        "messageRequestTimestamp": timestamp,
        "messageEncoding": "GSM",
        "messageType": "TRANSACTIONAL",
        "messageStatus": "CARRIER_UNREACHABLE",
        "messageStatusDescription": provider_response,
        "totalMessageParts": 1,
        "totalMessagePrice": 0.00581,
        "totalCarrierFee": 0.006,
    }

    return _pinpoint_callback(body)


def _ses_bounce_callback(reference, bounce_type, bounce_subtype=None):
    ses_message_body = {
        "bounce": {
            "bounceSubType": bounce_subtype or "General",
            "bounceType": bounce_type,
            "bouncedRecipients": [
                {
                    "action": "failed",
                    "diagnosticCode": "smtp; 550 5.1.1 user unknown",
                    "emailAddress": "bounce@simulator.amazonses.com",
                    "status": "5.1.1",
                }
            ],
            "feedbackId": "0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000",
            "remoteMtaIp": "123.123.123.123",
            "reportingMTA": "dsn; a7-31.smtp-out.eu-west-1.amazonses.com",
            "timestamp": "2017-11-17T12:14:05.131Z",
        },
        "mail": {
            "commonHeaders": {
                "from": ["TEST <TEST@smtp_user>"],
                "subject": "ses callback test",
                "to": ["bounce@simulator.amazonses.com"],
                "date": "Tue, 18 Feb 2020 14:34:52 +0000",
            },
            "destination": ["bounce@simulator.amazonses.com"],
            "headers": [
                {"name": "From", "value": "TEST <TEST@smtp_user>"},
                {"name": "To", "value": "bounce@simulator.amazonses.com"},
                {"name": "Subject", "value": "lambda test"},
                {"name": "MIME-Version", "value": "1.0"},
                {
                    "name": "Content-Type",
                    "value": 'multipart/alternative; boundary="----=_Part_596529_2039165601.1510920843367"',
                },
            ],
            "headersTruncated": False,
            "messageId": reference,
            "sendingAccountId": "12341234",
            "source": "TEST@smtp_user",
            "sourceArn": "arn:aws:ses:eu-west-1:12341234:identity/smtp_user",
            "sourceIp": "0.0.0.1",
            "timestamp": "2017-11-17T12:14:03.000Z",
        },
        "notificationType": "Bounce",
    }
    return {
        "Type": "Notification",
        "MessageId": "36e67c28-1234-1234-1234-2ea0172aa4a7",
        "TopicArn": "arn:aws:sns:eu-west-1:12341234:ses_notifications",
        "Subject": None,
        "Message": json.dumps(ses_message_body),
        "Timestamp": "2017-11-17T12:14:05.149Z",
        "SignatureVersion": "1",
        "Signature": "[REDACTED]",  # noqa
        "SigningCertUrl": "https://sns.eu-west-1.amazonaws.com/SimpleNotificationService-[REDACTED]].pem",
        "UnsubscribeUrl": "https://sns.eu-west-1.amazonaws.com/?Action=Unsubscribe&SubscriptionArn=[REDACTED]]",
        "MessageAttributes": {},
    }


def _sns_callback(body):
    return {
        "Type": "Notification",
        "MessageId": "8e83c020-1234-1234-1234-92a8ee9baa0a",
        "TopicArn": "arn:aws:sns:ca-central-1:12341234:ses_notifications",
        "Subject": None,
        "Message": json.dumps(body),
        "Timestamp": "2017-11-17T12:14:03.710Z",
        "SignatureVersion": "1",
        "Signature": "[REDACTED]",
        "SigningCertUrl": "https://sns.ca-central-1.amazonaws.com/SimpleNotificationService-[REDACTED].pem",
        "UnsubscribeUrl": "https://sns.ca-central-1.amazonaws.com/?Action=Unsubscribe&SubscriptionArn=[REACTED]",
        "MessageAttributes": {},
    }


def _pinpoint_callback(body):
    return {
        "Type": "Notification",
        "MessageId": "8e83c020-1234-1234-1234-92a8ee9baa0a",
        "TopicArn": "arn:aws:sns:ca-central-1:12341234:ses_notifications",
        "Subject": None,
        "Message": json.dumps(body),
        "Timestamp": "2017-11-17T12:14:03.710Z",
        "SignatureVersion": "1",
        "Signature": "[REDACTED]",
        "SigningCertUrl": "https://sns.ca-central-1.amazonaws.com/SimpleNotificationService-[REDACTED].pem",
        "UnsubscribeUrl": "https://sns.ca-central-1.amazonaws.com/?Action=Unsubscribe&SubscriptionArn=[REACTED]",
        "MessageAttributes": {},
    }
