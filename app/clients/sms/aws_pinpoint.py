from datetime import datetime
from logging import Logger
from time import monotonic
from typing import Tuple

import boto3
import botocore

from app.celery.exceptions import NonRetryableException
from app.clients.sms import (
    SmsClient,
    SmsClientResponseException,
    SmsStatusRecord,
    UNABLE_TO_TRANSLATE,
)
from app.constants import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_SENDING,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
    PINPOINT_PROVIDER,
    STATUS_REASON_BLOCKED,
    STATUS_REASON_INVALID_NUMBER,
    STATUS_REASON_RETRYABLE,
    STATUS_REASON_UNDELIVERABLE,
)
from app.exceptions import InvalidProviderException


class AwsPinpointException(SmsClientResponseException):
    pass


class AwsPinpointClient(SmsClient):
    """
    AwsSns pinpoint client
    """

    # https://docs.aws.amazon.com/pinpoint/latest/developerguide/event-streams-data-sms.html
    # Maps record_status to (status, status_reason)
    _sms_record_status_mapping = {
        'SUCCESSFUL': (NOTIFICATION_DELIVERED, None),
        'DELIVERED': (NOTIFICATION_DELIVERED, None),
        'PENDING': (NOTIFICATION_SENDING, None),
        'INVALID': (NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_INVALID_NUMBER),
        'UNREACHABLE': (NOTIFICATION_TEMPORARY_FAILURE, STATUS_REASON_RETRYABLE),
        'UNKNOWN': (NOTIFICATION_TEMPORARY_FAILURE, STATUS_REASON_RETRYABLE),
        'BLOCKED': (NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        'CARRIER_UNREACHABLE': (NOTIFICATION_TEMPORARY_FAILURE, STATUS_REASON_RETRYABLE),
        'SPAM': (NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        'INVALID_MESSAGE': (NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        'CARRIER_BLOCKED': (NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
        'TTL_EXPIRED': (NOTIFICATION_TEMPORARY_FAILURE, STATUS_REASON_RETRYABLE),
        'MAX_PRICE_EXCEEDED': (NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE),
        'OPTED_OUT': (NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_BLOCKED),
    }

    def __init__(self):
        self.name = 'pinpoint'

    def init_app(
        self,
        aws_pinpoint_app_id,
        aws_region,
        logger,
        origination_number,
        statsd_client,
    ):
        self._client = boto3.client('pinpoint', region_name=aws_region)
        self.aws_pinpoint_app_id = aws_pinpoint_app_id
        self.aws_region = aws_region
        self.origination_number = origination_number
        self.statsd_client = statsd_client
        self.logger: Logger = logger

    def get_name(self):
        return self.name

    def send_sms(
        self,
        to: str,
        content,
        reference,
        multi=True,
        sender=None,
        **kwargs,
    ):
        aws_phone_number = self.origination_number if sender is None else sender
        recipient_number = str(to)

        try:
            start_time = monotonic()
            response = self._post_message_request(recipient_number, content, aws_phone_number)

        except (botocore.exceptions.ClientError, Exception) as e:
            self.statsd_client.incr('clients.pinpoint.error')
            raise AwsPinpointException(str(e))
        else:
            self._validate_response(response['MessageResponse']['Result'][recipient_number])
            aws_reference = response['MessageResponse']['Result'][recipient_number]['MessageId']
            elapsed_time = monotonic() - start_time
            self.logger.info(
                'AWS Pinpoint SMS request using %s finished in %s for notificationId:%s and reference:%s',
                aws_phone_number,
                elapsed_time,
                reference,
                aws_reference,
            )
            self.statsd_client.timing('clients.pinpoint.request-time', elapsed_time)
            self.statsd_client.incr('clients.pinpoint.success')
            return aws_reference

    def _post_message_request(
        self,
        recipient_number,
        content,
        aws_phone_number,
    ):
        message_request_payload = {
            'Addresses': {recipient_number: {'ChannelType': 'SMS'}},
            'MessageConfiguration': {
                'SMSMessage': {'Body': content, 'MessageType': 'TRANSACTIONAL', 'OriginationNumber': aws_phone_number}
            },
        }

        return self._client.send_messages(
            ApplicationId=self.aws_pinpoint_app_id, MessageRequest=message_request_payload
        )

    def _validate_response(
        self,
        result: dict,
    ) -> None:
        # documentation of possible delivery statuses from Pinpoint can be found here:
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/pinpoint.html#Pinpoint.Client.send_messages
        delivery_status = result['DeliveryStatus']
        if delivery_status != 'SUCCESSFUL':
            self.statsd_client.incr(f'clients.pinpoint.delivery-status.{delivery_status.lower()}')

            error_message = f'StatusCode: {result["StatusCode"]}, StatusMessage:{result["StatusMessage"]}'

            if delivery_status in ['DUPLICATE', 'OPT_OUT', 'PERMANENT_FAILURE']:
                # indicates 'From' number doesn't exist for this Pinpoint account
                if 'provided number does not exist' in result['StatusMessage']:
                    raise InvalidProviderException(error_message)

                raise NonRetryableException(error_message)

            raise AwsPinpointException(error_message)

    def _get_status_mapping(self, record_status) -> Tuple[str, str]:
        if record_status not in self._sms_record_status_mapping:
            # This is a programming error, or Pinpoint's response format has changed.
            self.logger.critical('Unanticipated Pinpoint record status: %s', record_status)

        return self._sms_record_status_mapping.get(
            record_status, (NOTIFICATION_PERMANENT_FAILURE, STATUS_REASON_UNDELIVERABLE)
        )

    def _get_aws_status(
        self,
        event_type,
        record_status,
    ) -> Tuple[str, str]:
        """Get the status.

        Checks for opt out and then maps status and status reason.

        Args:
            event_type (str): AWS event type
            record_status (str): Mapping of record status to notification status

        Returns:
            Tuple[str, str]: status and status_reason
        """
        if event_type == '_SMS.OPTOUT':
            status = NOTIFICATION_PERMANENT_FAILURE
            status_reason = STATUS_REASON_BLOCKED
        else:
            status, status_reason = self._get_status_mapping(record_status)
        return status, status_reason

    def translate_delivery_status(
        self,
        delivery_status_message: str | dict[str, str],
    ) -> SmsStatusRecord:
        """Translate AWS Pinpoint delivery status

        Extracts relevant fields from the incoming message and translates the message into a standard format.

        Args:
            delivery_status_message (str | dict[str, str]): The incoming message

        Raises:
            NonRetryableException: The wrong message was passed to this method

        Returns:
            SmsStatusRecord: Object representing an sms status
        """
        if not isinstance(delivery_status_message, dict):
            self.logger.error('Did not receive pinpoint delivery status as a string')
            raise NonRetryableException(f'Incorrect datatype sent to pinpoint, {UNABLE_TO_TRANSLATE}')

        pinpoint_attributes = delivery_status_message['attributes']
        event_type = delivery_status_message['event_type']
        record_status = pinpoint_attributes['record_status']
        status, status_reason = self._get_aws_status(event_type, record_status)
        return SmsStatusRecord(
            None,
            pinpoint_attributes['message_id'],
            status,
            status_reason,
            PINPOINT_PROVIDER,
            pinpoint_attributes['number_of_message_parts'],
            delivery_status_message['metrics']['price_in_millicents_usd'],
            datetime.fromtimestamp(delivery_status_message['event_timestamp'] / 1000),
        )
