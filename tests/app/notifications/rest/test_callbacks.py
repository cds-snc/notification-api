import pytest
from flask import json


def dvla_post(client, data):
    return client.post(
        path='/notifications/letter/dvla',
        data=data,
        headers=[('Content-Type', 'application/json')]
    )


def test_dvla_callback_returns_400_with_invalid_request(client):
    data = json.dumps({"foo": "bar"})
    response = dvla_post(client, data)
    assert response.status_code == 400


def test_dvla_callback_autoconfirms_subscription(client, mocker):
    autoconfirm_mock = mocker.patch('app.notifications.notifications_letter_callback.autoconfirm_subscription')

    data = _sns_confirmation_callback()
    response = dvla_post(client, data)
    assert response.status_code == 200
    assert autoconfirm_mock.called


def test_dvla_callback_autoconfirm_does_not_call_update_letter_notifications_task(client, mocker):
    autoconfirm_mock = mocker.patch('app.notifications.notifications_letter_callback.autoconfirm_subscription')
    update_task = \
        mocker.patch('app.notifications.notifications_letter_callback.update_letter_notifications_statuses.apply_async')

    data = _sns_confirmation_callback()
    response = dvla_post(client, data)

    assert response.status_code == 200
    assert autoconfirm_mock.called
    assert not update_task.called


def test_dvla_callback_calls_does_not_update_letter_notifications_task_with_invalid_file_type(client, mocker):
    update_task = \
        mocker.patch('app.notifications.notifications_letter_callback.update_letter_notifications_statuses.apply_async')

    data = _sample_sns_s3_callback("bar.txt")
    response = dvla_post(client, data)

    assert response.status_code == 200
    assert not update_task.called


@pytest.mark.parametrize("filename",
                         ['Notify-20170411153023-rs.txt', 'Notify-20170411153023-rsp.txt'])
def test_dvla_rs_and_rsp_txt_file_callback_calls_update_letter_notifications_task(client, mocker, filename):
    update_task = mocker.patch(
        'app.notifications.notifications_letter_callback.update_letter_notifications_statuses.apply_async')
    daily_sorted_counts_task = mocker.patch(
        'app.notifications.notifications_letter_callback.record_daily_sorted_counts.apply_async')
    data = _sample_sns_s3_callback(filename)
    response = dvla_post(client, data)

    assert response.status_code == 200
    assert update_task.called
    update_task.assert_called_with([filename], queue='notify-internal-tasks')
    daily_sorted_counts_task.assert_called_with([filename], queue='notify-internal-tasks')


def test_dvla_ack_calls_does_not_call_letter_notifications_task(client, mocker):
    update_task = mocker.patch(
        'app.notifications.notifications_letter_callback.update_letter_notifications_statuses.apply_async')
    daily_sorted_counts_task = mocker.patch(
        'app.notifications.notifications_letter_callback.record_daily_sorted_counts.apply_async')
    data = _sample_sns_s3_callback('bar.ack.txt')
    response = dvla_post(client, data)

    assert response.status_code == 200
    update_task.assert_not_called()
    daily_sorted_counts_task.assert_not_called()


def _sample_sns_s3_callback(filename):
    message_contents = '''{"Records":[{"eventVersion":"2.0","eventSource":"aws:s3","awsRegion":"eu-west-1","eventTime":"2017-05-16T11:38:41.073Z","eventName":"ObjectCreated:Put","userIdentity":{"principalId":"some-p-id"},"requestParameters":{"sourceIPAddress":"8.8.8.8"},"responseElements":{"x-amz-request-id":"some-r-id","x-amz-id-2":"some-x-am-id"},"s3":{"s3SchemaVersion":"1.0","configurationId":"some-c-id","bucket":{"name":"some-bucket","ownerIdentity":{"principalId":"some-p-id"},"arn":"some-bucket-arn"},
            "object":{"key":"%s"}}}]}''' % (filename)  # noqa
    return json.dumps({
        "SigningCertURL": "foo.pem",
        "UnsubscribeURL": "bar",
        "Signature": "some-signature",
        "Type": "Notification",
        "Timestamp": "2016-05-03T08:35:12.884Z",
        "SignatureVersion": "1",
        "MessageId": "6adbfe0a-d610-509a-9c47-af894e90d32d",
        "Subject": "Amazon S3 Notification",
        "TopicArn": "sample-topic-arn",
        "Message": message_contents
    })


def _sns_confirmation_callback():
    return b'{\n    "Type": "SubscriptionConfirmation",\n    "MessageId": "165545c9-2a5c-472c-8df2-7ff2be2b3b1b",\n    "Token": "2336412f37fb687f5d51e6e241d09c805a5a57b30d712f794cc5f6a988666d92768dd60a747ba6f3beb71854e285d6ad02428b09ceece29417f1f02d609c582afbacc99c583a916b9981dd2728f4ae6fdb82efd087cc3b7849e05798d2d2785c03b0879594eeac82c01f235d0e717736",\n    "TopicArn": "arn:aws:sns:us-west-2:123456789012:MyTopic",\n    "Message": "You have chosen to subscribe to the topic arn:aws:sns:us-west-2:123456789012:MyTopic.\\nTo confirm the subscription, visit the SubscribeURL included in this message.",\n    "SubscribeURL": "https://sns.us-west-2.amazonaws.com/?Action=ConfirmSubscription&TopicArn=arn:aws:sns:us-west-2:123456789012:MyTopic&Token=2336412f37fb687f5d51e6e241d09c805a5a57b30d712f794cc5f6a988666d92768dd60a747ba6f3beb71854e285d6ad02428b09ceece29417f1f02d609c582afbacc99c583a916b9981dd2728f4ae6fdb82efd087cc3b7849e05798d2d2785c03b0879594eeac82c01f235d0e717736",\n    "Timestamp": "2012-04-26T20:45:04.751Z",\n    "SignatureVersion": "1",\n    "Signature": "EXAMPLEpH+DcEwjAPg8O9mY8dReBSwksfg2S7WKQcikcNKWLQjwu6A4VbeS0QHVCkhRS7fUQvi2egU3N858fiTDN6bkkOxYDVrY0Ad8L10Hs3zH81mtnPk5uvvolIC1CXGu43obcgFxeL3khZl8IKvO61GWB6jI9b5+gLPoBc1Q=",\n    "SigningCertURL": "https://sns.us-west-2.amazonaws.com/SimpleNotificationService-f3ecfb7224c7233fe7bb5f59f96de52f.pem"\n}'  # noqa
