import boto3
import json
import logging
import os

from botocore.client import BaseClient
from botocore.exceptions import ClientError

logger = logging.getLogger()
pinpoint_project_id = os.getenv('AWS_PINPOINT_APP_ID')
default_response_message = os.getenv('DEFAULT_RESPONSE_MESSAGE')
failure_topic_arn = os.getenv('FAILURE_TOPIC_ARN')


class OptInFailureException(Exception):
    pass


# context type is LambdaContext which reqs an import from a pkg we don't have, so omitted
def two_way_sms_handler(
    event: dict,
    context,
) -> dict:
    logger.setLevel(logging.INFO)

    region = os.getenv('AWS_REGION')
    pinpoint = boto3.client('pinpoint', region_name=region)

    sns = boto3.client('sns', region_name=region)
    start_keyword = os.getenv('START_KEYWORD')
    supported_keywords = json.loads(os.getenv('SUPPORTED_KEYWORDS'))

    try:
        for record in event['Records']:
            parsed_message = json.loads(record['Sns']['Message'])
            text_response = parsed_message['messageBody'].upper().strip()
            sender = parsed_message['destinationNumber']
            recipient_number = parsed_message['originationNumber']

            if text_response == start_keyword:
                return _opt_in_number(recipient_number, sns)
            if text_response not in supported_keywords:
                return _send_default_sms_message(recipient_number, sender, pinpoint)
    except OptInFailureException:
        # we handle opt-in failures in _make_sns_opt_in_request,
        # so we catch the error, handle it, raise it to stop execution, and pass to consider the lambda successful
        pass


def _opt_in_number(
    recipient_number: str,
    sns: BaseClient,
) -> dict:
    response = _make_sns_opt_in_request(recipient_number, sns)
    ok, parsed_response = _parse_response_sns(response, recipient_number)

    if ok:
        logging.info(f'Handler successfully with response {parsed_response}')
        return parsed_response
    else:
        raise Exception(f'SnsException: {parsed_response}')


def _send_default_sms_message(
    recipient_number,
    sender,
    pinpoint: BaseClient,
):
    response = _make_pinpoint_send_message_request(recipient_number, sender, pinpoint)
    logging.info(
        f'Handler successfully sent message with message ' f'{response["MessageResponse"]["Result"][recipient_number]}'
    )
    return response['MessageResponse']['Result'][recipient_number]


def _make_sns_opt_in_request(
    recipient_number: str,
    sns: BaseClient,
) -> dict:
    try:
        return sns.opt_in_phone_number(phoneNumber=recipient_number)
    except ClientError as error:
        message = {
            'sns_opt_in_request_id': error.response['ResponseMetadata']['RequestId'],
            'error_code': error.response['Error']['Code'],
            'error_message': error.response['Error']['Message'],
        }
        sns.publish(TopicArn=failure_topic_arn, Message=json.dumps(message), Subject='AWS SNS Opt-in Failure')
        logger.error(error)
        raise OptInFailureException(error)


def _parse_response_sns(
    response: dict,
    recipient_number: str,
) -> tuple:
    parsed_response = {
        'RequestId': response['ResponseMetadata']['RequestId'],
        'StatusCode': response['ResponseMetadata']['HTTPStatusCode'],
    }

    if 'MessageResponse' in response.keys():
        parsed_response.update(
            {
                'DeliveryStatus': response['MessageResponse']['Result'][recipient_number]['DeliveryStatus'],
                'DeliveryStatusCode': response['MessageResponse']['Result'][recipient_number]['StatusCode'],
                'DeliveryStatusMessage': response['MessageResponse']['Result'][recipient_number]['StatusMessage'],
            }
        )

    if 'DeliveryStatusCode' in parsed_response.keys() and parsed_response['DeliveryStatusCode'] in [400]:
        return False, parsed_response

    return True, parsed_response


def _make_pinpoint_send_message_request(
    recipient_number: str,
    sender: str,
    pinpoint: BaseClient,
) -> dict:
    return pinpoint.send_messages(
        ApplicationId=pinpoint_project_id,
        MessageRequest={
            'Addresses': {recipient_number: {'ChannelType': 'SMS'}},
            'MessageConfiguration': {
                'SMSMessage': {
                    'Body': default_response_message,
                    'MessageType': 'TRANSACTIONAL',
                    'OriginationNumber': sender,
                }
            },
        },
    )
