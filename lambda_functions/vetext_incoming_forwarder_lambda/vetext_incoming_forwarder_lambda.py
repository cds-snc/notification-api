"""This module is used to transfer incoming twilio requests to a Vetext endpoint"""

import json
import http.client
import ssl
import os
import logging
from urllib.parse import parse_qsl
from base64 import b64decode
import boto3

def vetext_incoming_forwarder_lambda_handler(event: any, context: any):
    """this method takes in an event passed in by either an alb or sqs.
        @param: event   -  contains data pertaining to an incoming sms from Twilio
        @param: context -  contains information regarding information
            regarding what triggered the lambda (context.invoked_function_arn).
    """

    try:
        # logging.debug(event)
        print(event)

        # Determine if the invoker of the lambda is SQS or ALB
        #   SQS will submit batches of records so there is potential for multiple events to be processed
        #   ALB will submit a single request but to simplify code, it will also return an array of event bodies
        if (event["requestContext"] and event["requestContext"]["elb"]):
            logging.info("alb invocation")
            event_bodies = get_body_from_alb_invocation(event)            
        elif event["Records"] and event["Records"][0].eventSource == 'aws:sqs':
            logging.info("sqs invoication")
            event_bodies = get_body_from_sqs_invocation(event)
        else:
            logging.error("Invalid Event. Expecting the source of an invocation to be from alb or sqs")

            push_to_sqs(event)

            return{
                'statusCode': 400
            }

        logging.debug(event_bodies)

        responses = []

        for event_body in event_bodies:            
            response = make_vetext_request(event_body)

            if response.status != 200:
                push_to_sqs(event)

            logging.debug(response.read().decode())

            responses.append(response)

        logging.debug(responses)
        
        return {
            'statusCode': 200
        }
    except KeyError as e:
        logging.exception(e)
        # Handle failed env variable
        print(f'Failed to find environmental variable: {e}')
        # Place request on SQS for processing after environment variable issue is resolved
        push_to_sqs(event)

        return {
            'statusCode': 424
        }
    except http.client.HTTPException as e:
        logging.exception(e)
        # Handle failed http request to vetext endpoint
        print(f'Failure with http connection or request: {e}')
        # Place request on SQS for processing after environment variable issue is resolved
        push_to_sqs(event)

        return{
            'statusCode':503
        }
    except Exception as e:
        logging.exception(e)        
        # Place request on dead letter queue so that it can be analyzed 
        #   for potential processing at a later time
        print(f'Unknown Failure: {e}')
        push_to_sqs(event)

        return{
            'statusCode':500
        }

def get_body_from_sqs_invocation(event):
    event_bodies = []
    for record in event.Records:
        # record is a sqs event that contains a body
        # body is an alb request that failed in an initial request
        # event is a json document with a body attribute that contains
        #   the payload of the twilio webhook
        # event["body"] is a base 64 encoded string
        # parse_qsl converts url-encoded strings to array of tuple objects
        # event_body takes the array of tuples and creates a dictionary
        event_body_decoded = parse_qsl(b64decode(record["body"]).decode('utf-8'))
        event_body = dict(event_body_decoded)
        event_bodies.append(event_body)

    return event_bodies

def get_body_from_alb_invocation(event):
    event_bodies = []

    # event is a json document with a body attribute that contains
    #   the payload of the twilio webhook
    # event["body"] is a base 64 encoded string
    # parse_qsl converts url-encoded strings to array of tuple objects
    # event_body takes the array of tuples and creates a dictionary
    event_body_decoded = parse_qsl(b64decode(event["body"]).decode('utf-8'))
    event_bodies.append(dict(event_body_decoded))

    return event_bodies
    

def read_from_ssm(key: str) -> str:
    boto_client = boto3.client('ssm')
    
    response = boto_client.get_parameter(
        Name=key,
        WithDecryption=True
    )

    logging.info(response)

    return response.get("Parameter", {}).get("Value", '')

def make_vetext_request(request_body):    
    connection = http.client.HTTPSConnection(os.environ.get('vetext_api_endpoint_domain'),  context = ssl._create_unverified_context())

    # Authorization is basic token authentication that is stored in environment.
    authToken = read_from_ssm(os.environ.get('vetext_api_auth_ssm_path'))

    logging.info(f'ssm key: {authToken}')

    headers = {
        'Content-type': 'application/json',
        'Authorization': 'Basic ' + authToken
    }

    body = {
            "accountSid": request_body.get("AccountSid", ""),
            "messageSid": request_body.get("MessageSid", ""),
            "messagingServiceSid": "",
            "to": request_body.get("To", ""),
            "from": request_body.get("From", ""),
            "messageStatus": request_body.get("SmsStatus", ""),
            "body": request_body.get("Body", "")
        }

    json_data = json.dumps(body)

    connection.request(
        'POST',
        os.environ.get('vetext_api_endpoint_path'),
        json_data,
        headers)

    response = connection.getresponse()

    return response    

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
    