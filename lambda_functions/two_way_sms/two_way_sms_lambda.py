import boto3
import json
import logging
import os

region = os.getenv("AWS_REGION")
pinpoint = boto3.client('pinpoint', region_name=region)
pinpoint_project_id = os.getenv("AWS_PINPOINT_APP_ID")
start_keyword = os.getenv("START_KEYWORD")
supported_keywords = os.getenv("SUPPORTED_KEYWORDS")
default_response_message = os.getenv("DEFAULT_RESPONSE_MESSAGE")


def two_way_sms_handler(event, context):
    try:
        for record in event["Records"]:
            parsed_message = json.loads(record["Sns"]["Message"])
            text_response = parsed_message["messageBody"]
            recipient_number = parsed_message["originationNumber"]
            sender = parsed_message["destinationNumber"]

            if start_keyword in text_response:
                # Assumes recipient number is prefixed with '+'
                endpoint_id = recipient_number[1:]
                pinpoint.update_endpoint(
                    ApplicationId=pinpoint_project_id,
                    EndpointId=endpoint_id,
                    EndpointRequest={
                        "Address": recipient_number,
                        "ChannelType": "SMS",
                        "OptOut": "NONE"
                    }
                )
            elif text_response not in supported_keywords:
                pinpoint.send_messages(
                    ApplicationId=pinpoint_project_id,
                    MessageRequest={
                        "Addresses": {
                            recipient_number: {
                                "ChannelType": "SMS"
                            }
                        },
                        "MessageConfiguration": {
                            "SMSMessage": {
                                "Body": default_response_message,
                                "MessageType": "TRANSACTIONAL",
                                "OriginationNumber": sender
                            }
                        }
                    }
                )

    except Exception as error:
        logging.error(f"Handler error when processing sms response: {error}")
