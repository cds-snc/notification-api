import json


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


def ses_notification_callback():
    return (
        '{\n  "Type" : "Notification",\n  "MessageId" : "ref1",'
        '\n  "TopicArn" : "arn:aws:sns:eu-west-1:123456789012:testing",'
        '\n  "Message" : "{\\"notificationType\\":\\"Delivery\\",'
        '\\"mail\\":{\\"timestamp\\":\\"2016-03-14T12:35:25.909Z\\",'
        '\\"source\\":\\"test@smtp_user\\",'
        '\\"sourceArn\\":\\"arn:aws:ses:eu-west-1:123456789012:identity/testing-notify\\",'
        '\\"sendingAccountId\\":\\"123456789012\\",'
        '\\"messageId\\":\\"ref1\\",'
        '\\"destination\\":[\\"testing@digital.cabinet-office.gov.uk\\"]},'
        '\\"delivery\\":{\\"timestamp\\":\\"2016-03-14T12:35:26.567Z\\",'
        '\\"processingTimeMillis\\":658,'
        '\\"recipients\\":[\\"testing@digital.cabinet-office.gov.uk\\"],'
        '\\"smtpResponse\\":\\"250 2.0.0 OK 1457958926 uo5si26480932wjc.221 - gsmtp\\",'
        '\\"reportingMTA\\":\\"a6-238.smtp-out.eu-west-1.amazonses.com\\"}}",'
        '\n  "Timestamp" : "2016-03-14T12:35:26.665Z",\n  "SignatureVersion" : "1",'
        '\n  "Signature" : "",'
        '\n  "SigningCertURL" : "https://sns.eu-west-1.amazonaws.com/SimpleNotificationService-bb750'
        'dd426d95ee9390147a5624348ee.pem",'
        '\n  "UnsubscribeURL" : "https://sns.eu-west-1.amazonaws.com/?Action=Unsubscribe&S'
        'subscriptionArn=arn:aws:sns:eu-west-1:302763885840:preview-emails:d6aad3ef-83d6-4cf3-a470-54e2e75916da"\n}'
    )


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


def _ses_bounce_callback(reference, bounce_type):
    ses_message_body = {
        "bounce": {
            "bounceSubType": "General",
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
