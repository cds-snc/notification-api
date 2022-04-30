"""This module is used to transfer incoming twilio requests to a Vetext endpoint"""

import json
import http.client
import os
from urllib.parse import parse_qsl
from base64 import b64decode
import boto3

def lambda_handler(event: any, context: any):
    """this method takes in an event passed in by either an alb or sqs.
        @param: event   -  contains data pertaining to an incoming sms from Twilio
        @param: context -  contains information regarding information
            regarding what triggered the lambda (context.invoked_function_arn).
    """

    try:
        connection = http.client.HTTPSConnection(os.environ.get('vetext_api_endpoint_domain'))

        # Authorization is basic token authentication that is stored in environment.
        headers = {
            'Content-type': 'application/json',
            'Authorization': os.environ.get('vetext_api_endpoint_auth')
        }

        # event is a json document with a body attribute that contains
        #   the payload of the twilio webhook
        # event["body"] is a base 64 encoded string
        # parse_qsl converts url-encoded strings to array of tuple objects
        # event_body takes the array of tuples and creates a dictionary
        event_body_decoded = parse_qsl(b64decode(event["body"]).decode('utf-8'))
        event_body = dict(event_body_decoded)

        body = {
            "accountSid": event_body.get("AccountSid", ""),
            "messageSid": event_body.get("MessageSid", ""),
            "messagingServiceSid": "",
            "to": event_body.get("To", ""),
            "from": event_body.get("From", ""),
            "messageStatus": event_body.get("SmsStatus", ""),
            "body": event_body.get("Body", "")
        }

        json_data = json.dumps(body)

        connection.request(
            'POST',
            os.environ.get('vetext_api_endpoint_path'),
            json_data,
            headers)

        response = connection.getresponse()

        if response.status != 200:
            push_to_sqs(event)

        return {
            'statusCode': response.status,
            'body': response.read().decode()
        }
    except KeyError as e:
        print(f'Failed to find environmental variable: {e}')
        # Handle failed env variable
        return {
            'statusCode': 424,
            'body': "Missing env variable"
        }
    except http.client.HTTPException as e:
        print(f'Failure with http connection or request: {e}')
        push_to_sqs(event)
        return {
            'statusCode': 200,
            'body': "Moved to queue"
        }

def push_to_sqs(event):
    """Places event on queue to be retried at a later time"""
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
