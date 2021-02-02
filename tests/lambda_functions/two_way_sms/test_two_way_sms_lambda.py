# import os

# from lambda_functions.two_way_sms.two_way_sms_lambda import two_way_sms_handler


def test_two_way_sms_handler_with_sns(mocker):
    # mocker.patch.dict(os.environ, {'AWS_REGION': 'us-east-2'})
    # mock_sns = mocker.Mock()
    # mock_sns.opt_in_phone_number.return_value = {
    #     'ResponseMetadata': {
    #         'RequestId': 'ce2b0621-679b-44ad-bd08-5a000216da0f',
    #         'HTTPStatusCode': 200,
    #         'HTTPHeaders': {
    #             'date': 'Fri, 29 Jan 2021 22:05:47 GMT',
    #             'content-type': 'application/json',
    #             'content-length': '303',
    #             'connection': 'keep-alive',
    #             'x-amzn-requestid': 'ce2b0621-679b-44ad-bd08-5a000216da0f',
    #             'access-control-allow-origin': '*',
    #             'x-amz-apigw-id': 'Z7n9QH0uPHMFV5Q=',
    #             'cache-control': 'no-store',
    #             'x-amzn-trace-id': 'Root=1-601486bb-4a8da6be26d00f6270d4372e'
    #         },
    #         'RetryAttempts': 0
    #     },
    #     'MessageResponse': {
    #         'ApplicationId': 'df55c01206b742d2946ef226410af94f',
    #         'RequestId': 'ce2b0621-679b-44ad-bd08-5a000216da0f',
    #         'Result': {
    #             '+12677023245': {
    #                 'DeliveryStatus': 'SUCCESSFUL',
    #                 'MessageId': '7jh3evtoejd6i74omsm6lehh6ef0bc9mib25sf80',
    #                 'StatusCode': 200,
    #                 'StatusMessage': 'MessageId: 7jh3evtoejd6i74omsm6lehh6ef0bc9mib25sf80'
    #             }
    #         }
    #     }
    # }
    #
    # mock_boto = mocker.Mock()
    # mock_boto.client.return_value = mock_sns
    #
    # mocker.patch('lambda_functions.two_way_sms.two_way_sms_lambda.boto3', new=mock_boto)
    #
    # event = {
    #     "Records": [
    #         {
    #             "EventVersion": "1.0",
    #             "EventSubscriptionArn": "some_arn",
    #             "EventSource": "aws:sns",
    #             "Sns": {
    #                 "SignatureVersion": "1",
    #                 "Timestamp": "2019-01-02T12:45:07.000Z",
    #                 "Signature": "some signature",
    #                 "SigningCertUrl": "some_url",
    #                 "MessageId": "95df01b4-ee98-5cb9-9903-4c221d41eb5e",
    #                 "Message": {
    #                     "messageBody": "a message body",
    #                     "destinationNumber": "+18880001111",
    #                     "originationNumber": "+18881112222"
    #                 },
    #                 "MessageAttributes": {
    #                     "Test": {
    #                         "Type": "String",
    #                         "Value": "TestString"
    #                     },
    #                     "TestBinary": {
    #                         "Type": "Binary",
    #                         "Value": "TestBinary"
    #                     }
    #                 },
    #                 "Type": "Notification",
    #                 "UnsubscribeUrl": "some_url",
    #                 "TopicArn": "arn:aws:sns:us-east-2:123456789012:sns-lambda",
    #                 "Subject": "TestInvoke"
    #             }
    #         }
    #     ]
    # }
    #
    # response = two_way_sms_handler(event, mocker.Mock())
    # assert response['statusCode'] == 200
    #
    # mock_sns.opt_in_phone_number.assert_called_once()
    pass
