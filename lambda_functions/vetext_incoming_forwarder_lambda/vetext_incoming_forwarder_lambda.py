"""This module is used to transfer incoming twilio requests to a Vetext endpoint"""

import json
import http.client
import ssl
import os
import logging
from urllib.parse import parse_qsl
from base64 import b64decode
import boto3

logging.getLogger().setLevel(logging.DEBUG)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

def vetext_incoming_forwarder_lambda_handler(event: any, context: any):
    """this method takes in an event passed in by either an alb or sqs.
        @param: event   -  contains data pertaining to an incoming sms from Twilio
        @param: context -  contains information regarding information
            regarding what triggered the lambda (context.invoked_function_arn).
    """

    try:
        logger.debug(event)
        # Determine if the invoker of the lambda is SQS or ALB
        #   SQS will submit batches of records so there is potential for multiple events to be processed
        #   ALB will submit a single request but to simplify code, it will also return an array of event bodies
        if "requestContext" in event and "elb" in event["requestContext"]:
            logger.info("alb invocation")
            event_bodies = process_body_from_alb_invocation(event)            
        elif "Records" in event:
            logger.info("sqs invoication")
            event_bodies = process_body_from_sqs_invocation(event)
        else:
            logger.error("Invalid Event. Expecting the source of an invocation to be from alb or sqs")
            logger.error(json.dumps(event))

            return{
                'statusCode': 400
            }

        logger.info("Successfully processed event to event_bodies")
        logger.debug(event_bodies)

        responses = []

        for event_body in event_bodies:       
            try:      
                logger.info("Making call to VeText")
                logger.debug(f"Processing event_body: {event_body}")
                response = make_vetext_request(event_body)

                if response.status != 200:
                    logger.info("VeText call failed. Moving event body to failover queue")
                    push_to_sqs(event_body)
                
                responses.append(response)
            except http.client.HTTPException as e:
                logger.info("HttpException With Call To VeText")
                logger.info(json.dumps(event_body))
                logger.exception(e)                                
                push_to_sqs(event_body)
            except Exception as e:
                logger.info("General Exception With Call to VeText")
                logger.info(json.dumps(event_body))
                logger.exception(e)                        
                push_to_sqs(event_body)

        logger.debug(responses)
        
        return {
            'statusCode': 200
        }
    except KeyError as e:
        logger.info("Key Error")
        logger.info(json.dumps(event))
        logger.exception(e)
        
        return {
            'statusCode': 424
        }   
    except Exception as e:
        logger.info("General Exception")
        logger.info(json.dumps(event))
        logger.exception(e)        
        
        return{
            'statusCode':500
        }

def process_body_from_sqs_invocation(event):
    event_bodies = []
    for record in event["Records"]:
        # record is a sqs event that contains a body
        # body is an alb request that failed in an initial request
        # event is a json document with a body attribute that contains
        #   the payload of the twilio webhook
        # event["body"] is a base 64 encoded string
        # parse_qsl converts url-encoded strings to array of tuple objects
        # event_body takes the array of tuples and creates a dictionary
        event_body = dict(record["body"])
        event_bodies.append(event_body)
    
    return event_bodies

def process_body_from_alb_invocation(event):
    event_bodies = []

    # event is a json document with a body attribute that contains
    #   the payload of the twilio webhook
    # event["body"] is a base 64 encoded string
    # parse_qsl converts url-encoded strings to array of tuple objects
    # event_body takes the array of tuples and creates a dictionary
    event_body_decoded = parse_qsl(b64decode(event["body"]).decode('utf-8'))
    logger.info(f"Decoded event_body {event_body_decoded}")
    event_body = dict(event_body_decoded)
    
    if 'AddOns' in event_body:
        event_body.pop('AddOns')
   
    event_bodies.append(event_body)

    return event_bodies    

def read_from_ssm(key: str) -> str:
    ssm_client = boto3.client('ssm')
    
    response = ssm_client.get_parameter(
        Name=key,
        WithDecryption=True
    )

    return response.get("Parameter", {}).get("Value", '')

def make_vetext_request(request_body):    
    # We have been directed by the VeText team to ignore SSL validation
    #   that is why we use the ssl._create_unverified_context method
    connection = http.client.HTTPSConnection(os.environ.get('vetext_api_endpoint_domain'),  context = ssl._create_unverified_context())
    logger.info("generated connection to VeText")

    # Authorization is basic token authentication that is stored in environment.
    auth_token = read_from_ssm(os.environ.get('vetext_api_auth_ssm_path'))
    logger.info("Retrieved AuthToken from SSM")
    
    headers = {
        'Content-type': 'application/json',
        'Authorization': 'Basic ' + auth_token
    }

    body = {
            "accountSid": request_body.get("AccountSid", ""),
            "messageSid": request_body.get("MessageSid", ""),
            "messagingServiceSid": request_body.get("MessagingServiceSid", ""),
            "to": request_body.get("To", ""),
            "from": request_body.get("From", ""),
            "messageStatus": request_body.get("SmsStatus", ""),
            "body": request_body.get("Body", "")
        }

    json_data = json.dumps(body)

    logger.info("Making POST Request to VeText using: " + os.environ.get('vetext_api_endpoint_domain') + os.environ.get('vetext_api_endpoint_path'))
    logger.debug(f"POST body: {json_data}")
    
    connection.request(
        'POST',
        os.environ.get('vetext_api_endpoint_path'),
        json_data,
        headers)
    
    response = connection.getresponse()
    
    logger.info(f"VeText call complete, with response: {str(response.status)}")
    logger.debug(response.read().decode())

    return response    

def push_to_sqs(event_body):
    """Places event body dictionary on queue to be retried at a later time"""
    logger.info("Placing event_body on retry queue")

    sqs = boto3.client('sqs')
    queue_url = os.environ.get('vetext_request_drop_sqs_url')
    logger.debug(f"Retrieved queue_url: {queue_url}")

    queue_msg = json.dumps(event_body)
    queue_msg_attrs = {
        'source': {
            'DataType': 'String',
            'StringValue': 'twilio'
        }
    }

    sqs.send_message(QueueUrl=queue_url,
                    MessageAttributes=queue_msg_attrs,
                    MessageBody=queue_msg)
    
    logger.info("Completed enqueue of message to retry queue")
    