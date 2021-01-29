import boto3
import json
import logging
import os

region = os.getenv("AWS_REGION")
pinpoint = boto3.client('pinpoint', region_name=region)
pinpoint_project_id = os.getenv("AWS_PINPOINT_APP_ID")
sns = boto3.client('sns')
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

            if start_keyword in text_response.upper():
                response = sns.opt_in_phone_number(
                    phoneNumber=recipient_number
                )
                parsed_response = {
                    'RequestId': response['ResponseMetadata']['RequestId'],
                    'StatusCode': response['ResponseMetadata']['HTTPStatusCode'],
                    'DeliveryStatus': response['MessageResponse'][recipient_number]['DeliveryStatus'],
                    'StatusMessage': response['MessageResponse'][recipient_number]['DeliveryStatus']

                }
                logging.info(f"Handler successfully with response {parsed_response}")
                return parsed_response
            elif text_response.upper() not in supported_keywords:
                response = pinpoint.send_messages(
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

                response_body = response['MessageResponse']['Result'][recipient_number]
                logging.info(f"Handler successfully sent message with message {response_body}")
                return response_body

    except Exception as error:
        logging.error(f"Handler error when processing sms response: {error}")
