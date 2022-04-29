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

    connection = http.client.HTTPSConnection(
        os.environ['vetext_api_endpoint_domain'])

    # Authorization is basic token authentication that is stored in environment.
    headers = {
        'Content-type': 'application/json',
        'Authorization': os.environ['vetext_api_endpoint_auth']
    }

    # event["body"] is a url-encoded string.
    #   parse_qs converts url-encoded strings to dictionary objects
    event_body = urllib.parse.parse_qs(event["body"])

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
        os.environ['vetext_api_endpoint_path'],
        json_data,
        headers)

    response = connection.getresponse()

    if response.status != 200:
        sqs = boto3.client('sqs')
        queue_url = os.environ['vetext_request_drop_sqs_url']

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
