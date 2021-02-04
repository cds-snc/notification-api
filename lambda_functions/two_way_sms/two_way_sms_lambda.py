import boto3
import json
import logging
import os

logger = logging.getLogger()
region = os.getenv("AWS_REGION")
pinpoint = boto3.client('pinpoint', region_name=region)
pinpoint_project_id = os.getenv("AWS_PINPOINT_APP_ID")
sns = boto3.client('sns', region_name=region)
start_keyword = os.getenv("START_KEYWORD")
supported_keywords = os.getenv("SUPPORTED_KEYWORDS")
default_response_message = os.getenv("DEFAULT_RESPONSE_MESSAGE")


def two_way_sms_handler(event: dict, context: dict) -> dict:
    logger.setLevel(logging.INFO)

    try:
        for record in event["Records"]:
            parsed_message = json.loads(record["Sns"]["Message"])
            text_response = parsed_message["messageBody"]
            sender = parsed_message["destinationNumber"]
            recipient_number = parsed_message["originationNumber"]

            if start_keyword in text_response.upper():
                return _opt_in_number(recipient_number)
            elif text_response.upper() not in supported_keywords:
                return _send_default_sms_message(recipient_number, sender)

    except Exception as error:
        logging.error(f"Handler error when processing sms response: {error}")


def _opt_in_number(recipient_number: str) -> dict:
    response = _make_sns_opt_in_request(recipient_number)
    response.raise_for_status()

    parsed_response = _parse_response_sns(response, recipient_number)

    if parsed_response["DeliveryStatus"] in [200]:
        logging.info(f"Handler successfully with response {parsed_response}")
        return parsed_response
    else:
        raise Exception(f"SnsException: {parsed_response}")


def _send_default_sms_message(recipient_number, sender):
    response = _make_pinpoint_send_message_request(recipient_number, sender)
    logging.info(f"Handler successfully sent message with message "
                 f"{response['MessageResponse']['Result'][recipient_number]}")
    return response['MessageResponse']['Result'][recipient_number]


def _make_sns_opt_in_request(recipient_number: str) -> dict:
    return sns.opt_in_phone_number(
        phoneNumber=recipient_number
    )


def _parse_response_sns(response: dict, recipient_number: str) -> dict:
    parsed_response = {
        'RequestId': response['ResponseMetadata']['RequestId'],
        'StatusCode': response['ResponseMetadata']['HTTPStatusCode']
    }

    if 'MessageResponse' in response.values():
        parsed_response.update({
            'DeliveryStatus': response['MessageResponse'][recipient_number]['DeliveryStatus'],
            'StatusMessage': response['MessageResponse'][recipient_number]['StatusMessage']
        })

    return parsed_response


def _make_pinpoint_send_message_request(recipient_number: str, sender: str) -> dict:
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