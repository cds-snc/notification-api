import boto3
import json
import logging
import os

from botocore.client import BaseClient

logger = logging.getLogger()
pinpoint_project_id = os.getenv("AWS_PINPOINT_APP_ID")
default_response_message = os.getenv("DEFAULT_RESPONSE_MESSAGE")


# context type is LambdaContext which reqs an import from a pkg we don't have, so omitted
def two_way_sms_handler(event: dict, context) -> dict:
    logger.setLevel(logging.INFO)

    region = os.getenv("AWS_REGION")
    pinpoint = boto3.client('pinpoint', region_name=region)

    sns = boto3.client('sns', region_name=region)
    start_keyword = os.getenv("START_KEYWORD")
    supported_keywords = os.getenv("SUPPORTED_KEYWORDS")

    try:
        for record in event["Records"]:
            parsed_message = json.loads(record["Sns"]["Message"])
            text_response = parsed_message["messageBody"]
            sender = parsed_message["destinationNumber"]
            recipient_number = parsed_message["originationNumber"]

            if start_keyword in text_response.upper():
                return _opt_in_number(recipient_number, sns)
            elif text_response.upper() not in supported_keywords:
                return _send_default_sms_message(recipient_number, sender, pinpoint)

    except Exception as error:
        logging.error(f"Handler error when processing sms response: {error}")


def _opt_in_number(recipient_number: str, sns: BaseClient) -> dict:
    response = _make_sns_opt_in_request(recipient_number, sns)
    ok, parsed_response = _parse_response_sns(response, recipient_number)

    if ok:
        logging.info(f"Handler successfully with response {parsed_response}")
        return parsed_response
    else:
        raise Exception(f"SnsException: {parsed_response}")


def _send_default_sms_message(recipient_number, sender, pinpoint: BaseClient):
    response = _make_pinpoint_send_message_request(recipient_number, sender, pinpoint)
    logging.info(f"Handler successfully sent message with message "
                 f"{response['MessageResponse']['Result'][recipient_number]}")
    return response['MessageResponse']['Result'][recipient_number]


def _make_sns_opt_in_request(recipient_number: str, sns: BaseClient) -> dict:
    return sns.opt_in_phone_number(
        phoneNumber=recipient_number
    )


def _parse_response_sns(response: dict, recipient_number: str) -> tuple:
    parsed_response = {
        'RequestId': response['ResponseMetadata']['RequestId'],
        'StatusCode': response['ResponseMetadata']['HTTPStatusCode']
    }

    if 'MessageResponse' in response.keys():
        parsed_response.update({
            'DeliveryStatus': response['MessageResponse']['Result'][recipient_number]['DeliveryStatus'],
            'DeliveryStatusCode': response['MessageResponse']['Result'][recipient_number]['StatusCode'],
            'DeliveryStatusMessage': response['MessageResponse']['Result'][recipient_number]['StatusMessage']
        })

    if parsed_response["DeliveryStatusCode"] in [400]:
        return False, parsed_response

    return True, parsed_response


def _make_pinpoint_send_message_request(recipient_number: str, sender: str, pinpoint: BaseClient) -> dict:
    return pinpoint.send_messages(
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
