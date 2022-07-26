"""This module is used to transfer incoming twilio requests to a Vetext endpoint"""

import json
import http.client
import ssl
import os
import logging
from urllib.parse import parse_qsl
from base64 import b64decode
import boto3

logger = logging.getLogger("vetext_incoming_forwarder_lambda")
logger.setLevel(logging.DEBUG)

def vetext_incoming_forwarder_lambda_handler(event: dict, context: any):
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
            logger.info("sqs invocation")
            event_bodies = process_body_from_sqs_invocation(event)
        else:
            logger.error("Invalid Event. Expecting the source of an invocation to be from alb or sqs")
            logger.debug(event)

            return{
                'statusCode': 400
            }

        logger.info("Successfully processed event to event_bodies")
        logger.debug(event_bodies)

        responses = []

        for event_body in event_bodies:       
            logger.debug(f"Processing event_body: {event_body}")
            
            response = make_vetext_request(event_body)                
            
            if response is None:
                push_to_sqs(event_body)
            
            responses.append(response)          

        logger.debug(responses)
        
        return {
            'statusCode': 200
        }
    except KeyError as e:
        logger.error(event)
        logger.exception(e)
        
        return {
            'statusCode': 424
        }   
    except Exception as e:        
        logger.error(event)
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
        try: 
            event_body = record.get("body", "")

            if not event_body:
                logger.info("event_body from sqs record was not present")
                logger.debug(record)
                continue

            logger.debug(f"Processing record body from SQS: {event_body}")
            event_body = json.loads(event_body)
            logger.info("Successfully converted record body from sqs to json")
            event_bodies.append(event_body)
        except Exception as e:
            logger.error("Failed to load event from sqs")
            logger.exception(e)        
            push_to_sqs(event_body)
    
    return event_bodies

def process_body_from_alb_invocation(event):
    # event is a json document with a body attribute that contains
    #   the payload of the twilio webhook
    # event["body"] is a base 64 encoded string
    # parse_qsl converts url-encoded strings to array of tuple objects
    # event_body takes the array of tuples and creates a dictionary
    event_body_encoded = event.get("body", "")

    if not event_body_encoded:
        logger.info("event_body from alb record was not present")
        logger.debug(event)        

    event_body_decoded = parse_qsl(b64decode(event_body_encoded).decode('utf-8'))
    logger.debug(f"Decoded event body {event_body_decoded}")

    event_body = dict(event_body_decoded)
    logger.debug(f"Converted body to dictionary: {event_body}")

    if 'AddOns' in event_body:        
        logger.info(f"AddOns present in event_body: {event_body['AddOns']}")
        del event_body['AddOns']
        logger.info("Removed AddOns from event_body")
   
    return [event_body]

def read_from_ssm(key: str) -> str:
    try: 
        ssm_client = boto3.client('ssm')
        
        response = ssm_client.get_parameter(
            Name=key,
            WithDecryption=True
        )

        return response.get("Parameter", {}).get("Value", '')
    except Exception as e:
        logger.error("General Exception With Call to VeText")                
        logger.exception(e)       
        return ''

def make_vetext_request(request_body):    
    # We have been directed by the VeText team to ignore SSL validation
    #   that is why we use the ssl._create_unverified_context method

    ssm_path = os.getenv('vetext_api_auth_ssm_path')
    if ssm_path is None:
        logger.error("Unable to retrieve vetext_api_auth_ssm_path from env variables")
        return None

    domain = os.getenv('vetext_api_endpoint_domain')
    if domain is None:
        logger.error("Unable to retrieve vetext_api_endpoint_domain from env variables")
        return None

    path = os.getenv('vetext_api_endpoint_path')
    if path is None:
        logger.error("Unable to retrieve vetext_api_endpoint_path from env variables")
        return None    
    
    # Authorization is basic token authentication that is stored in environment.
    auth_token = read_from_ssm(ssm_path)
    
    if auth_token == '':
        logger.error("Unable to retrieve auth token from SSM")
        return None
    
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

    logger.info(f"Making POST Request to VeText using: ${domain}${path}")
    logger.debug(f"json dumps: {json_data}")

    try:
        connection = http.client.HTTPSConnection(domain,  context = ssl._create_unverified_context())
        logger.info("generated connection to VeText")
        
        connection.request(
            'POST',
            path,
            json_data,
            headers)

        response = connection.getresponse()
        
        logger.info(f"VeText call complete with response: {response.status}")
        logger.debug(f"VeText response: {response}")

        if response.status == 200:
            return response        

        logger.error("VeText call failed.")
    except http.client.HTTPException as e:
        logger.error("HttpException With Call To VeText")                
        logger.exception(e)                                                     
    except Exception as e:
        logger.error("General Exception With Call to VeText")                
        logger.exception(e)                                                
    finally:
        connection.close()

    return None

def push_to_sqs(event_body):
    """Places event body dictionary on queue to be retried at a later time"""
    logger.info("Placing event_body on retry queue")
    logger.debug(f"Preparing for SQS: {event_body}")

    try:
        sqs = boto3.client('sqs')
        queue_url = os.getenv('vetext_request_drop_sqs_url')
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
    except Exception as e:
        logger.error("Push to SQS Exception")
        logger.error(event_body)
        logger.exception(e)        
    