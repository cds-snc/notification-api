"""This module is used to transfer incoming twilio requests to a Vetext endpoint"""

import json
import http.client
import os
import urllib.parse
import boto3
import logging

def lambda_handler(event: any, context: any):
    """this method takes in an event passed in by either an alb or sqs.
        @param: event   -  contains data pertaining to an incoming sms from Twilio
        @param: context -  contains information regarding information
            regarding what triggered the lambda (context.invoked_function_arn).
    """

    try:
        assert os.environ.get('vetext_api_endpoint_domain') is not None, 'vetext_api_endpoint_domain'
        assert os.environ.get('vetext_api_endpoint_auth') is not None, 'vetext_api_endpoint_auth'
        assert os.environ.get('vetext_api_endpoint_path') is not None, 'vetext_api_endpoint_path'
        assert os.environ.get('vetext_request_drop_sqs_url') is not None, 'vetext_api_endpoint_path'
    except AssertionError as e:
        print(f'Failed to find environmental variable: {e}')
        # Handle failed env variable
        return {
            'statusCode': 424,
            'body': "Missing env variable"
        }

    connection = http.client.HTTPSConnection(os.environ.get('vetext_api_endpoint_domain'))

    # Authorization is basic token authentication that is stored in environment.
    headers = {
        'Content-type': 'application/json',
        'Authorization': os.environ.get('vetext_api_endpoint_auth')
    }

    # event["body"] is a url-encoded string.
    #   parse_qs converts url-encoded strings to dictionary objects
    event_body = urllib.parse.parse_qs(event["body"])
    
    body = {
        "accountSid": event_body.get("AccountSid", [""])[0],
        "messageSid": event_body.get("MessageSid", [""])[0],
        "messagingServiceSid": "",
        "to": event_body.get("To", [""])[0],
        "from": event_body.get("From", [""])[0],
        "messageStatus": event_body.get("SmsStatus", [""])[0],
        "body": event_body.get("Body", [""])[0]
    }

    json_data = json.dumps(body)

    connection.request(
        'POST',
        os.environ.get('vetext_api_endpoint_path'),
        json_data,
        headers)

    response = connection.getresponse()

    if response.status != 200:
        sqs = boto3.client('sqs')
        queue_url = os.environ.get('vetext_request_drop_sqs_url')

        queue_msg = json.dumps(event)
        queue_msg_attrs = {
            'source': {
                'DataType': 'String',
                'StringValue': 'twilio'
            }
        }

        sqs.send_message(QueueUrl=queue_url,
                         MessageAttributes=queue_msg_attrs,
                         MessageBody=queue_msg)
        return {
            'statusCode': response.status,
            'body': response.read().decode()
        }        
    
    return {
        'statusCode': 200,
        'body': response.read().decode()
    }
