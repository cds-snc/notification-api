from datetime import datetime
from logging import Logger
from time import monotonic
from typing import Tuple

import boto3
import botocore
import botocore.exceptions

from app.celery.exceptions import NonRetryableException, RetryableException
from app.clients.sms import (
    SmsClient,
    SmsClientResponseException,
    SmsStatusRecord,
    UNABLE_TO_TRANSLATE,
)
from app.constants import (
    INTERNAL_PROCESSING_LIMIT,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_SENDING,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
    PINPOINT_PROVIDER,
    SMS_TYPE,
    STATSD_FAILURE,
    STATSD_RETRYABLE,
    STATSD_SUCCESS,
    STATUS_REASON_BLOCKED,
    STATUS_REASON_INVALID_NUMBER,
    STATUS_REASON_RETRYABLE,
    STATUS_REASON_UNDELIVERABLE,
)
from app.exceptions import InvalidProviderException
from app.feature_flags import FeatureFlag, is_feature_enabled


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
    # https://boto3.amazonaws.com/v1/documentation/api/latest/guide/retries.html#available-retry-modes
    _retryable_v1_codes = ('429', '500', '502', '503', '504', '509')
    _retryable_v1_request_statuses = ('THROTTLED', 'TEMPORARY_FAILURE', 'UNKNOWN_FAILURE')
    _non_retryable_v1_request_statuses = ('PERMANENT_FAILURE', 'OPT_OUT', 'DUPLICATE')

    def __init__(self):
        self.name = PINPOINT_PROVIDER

    def init_app(
        self,
        aws_pinpoint_app_id,
        aws_pinpoint_v2_configset,
        aws_region,
        logger,
        origination_number,
        statsd_client,
    ):
        self._pinpoint_client = boto3.client('pinpoint', region_name=aws_region)
        self._pinpoint_sms_voice_v2_client = boto3.client('pinpoint-sms-voice-v2', region_name=aws_region)
        self.aws_pinpoint_app_id = aws_pinpoint_app_id
        self.aws_pinpoint_v2_configset = aws_pinpoint_v2_configset
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
        reference,  # Notification id
        multi=True,
        sender=None,
        created_at=datetime.utcnow(),
        **kwargs,
    ):
        # Avoid circular imports
        from app import redis_store
        from app.utils import get_redis_retry_key

        aws_phone_number = self.origination_number if sender is None else sender
        recipient_number = str(to)

        # Log how long it spent in our system before we sent it if this is not an SMS retry
        if redis_store.get(get_redis_retry_key(reference)) is None:
            total_time = (datetime.utcnow() - created_at).total_seconds()
            if total_time >= INTERNAL_PROCESSING_LIMIT:
                self.logger.warning(
                    'Exceeded maximum total time (%s) to send %s notification: %s seconds',
                    INTERNAL_PROCESSING_LIMIT,
                    SMS_TYPE,
                    total_time,
                )
            else:
                self.logger.info(
                    'Total time spent to send %s notification: %s seconds',
                    SMS_TYPE,
                    total_time,
                )
        start_time = monotonic()

        try:
            response = self._post_message_request(recipient_number, content, aws_phone_number)
        except (botocore.exceptions.ClientError, Exception) as e:
            self.statsd_client.incr('clients.pinpoint.error')
            msg = str(e)
            if any(code in msg for code in AwsPinpointClient._retryable_v1_codes):
                self.logger.warning('Encountered a Retryable exception: %s - %s', type(e).__class__.__name__, msg)
                self.statsd_client.incr(f'{SMS_TYPE}.{PINPOINT_PROVIDER}_request.{STATSD_RETRYABLE}.{aws_phone_number}')
                raise RetryableException from e
            else:
                self.logger.exception('Encountered an unexpected exception sending Pinpoint SMS')
                self.statsd_client.incr(f'{SMS_TYPE}.{PINPOINT_PROVIDER}_request.{STATSD_FAILURE}.{aws_phone_number}')
                raise AwsPinpointException(str(e))
        else:
            if is_feature_enabled(FeatureFlag.PINPOINT_SMS_VOICE_V2):
                # The V2 response doesn't contain additional fields to validate.
                aws_reference = response['MessageId']
            else:
                self._validate_response(response['MessageResponse']['Result'][recipient_number], aws_phone_number)
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
            self.statsd_client.incr(f'{SMS_TYPE}.{PINPOINT_PROVIDER}_request.{STATSD_SUCCESS}.{aws_phone_number}')
            return aws_reference

    def _post_message_request(
        self,
        recipient_number,
        content,
        aws_phone_number,
    ):
        if is_feature_enabled(FeatureFlag.PINPOINT_SMS_VOICE_V2):
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/pinpoint-sms-voice-v2/client/send_text_message.html  # noqa
            self.logger.debug('Sending an SMS notification with the PinpointSMSVoiceV2 client')

            return self._pinpoint_sms_voice_v2_client.send_text_message(
                DestinationPhoneNumber=recipient_number,
                OriginationIdentity=aws_phone_number,
                MessageBody=content,
                ConfigurationSetName=self.aws_pinpoint_v2_configset,
            )
        else:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/pinpoint/client/send_messages.html#send-messages  # noqa
            self.logger.debug('Sending an SMS notification with the Pinpoint client')

            message_request_payload = {
                'Addresses': {recipient_number: {'ChannelType': 'SMS'}},
                'MessageConfiguration': {
                    'SMSMessage': {
                        'Body': content,
                        'MessageType': 'TRANSACTIONAL',
                        'OriginationNumber': aws_phone_number,
                    }
                },
            }

            return self._pinpoint_client.send_messages(
                ApplicationId=self.aws_pinpoint_app_id, MessageRequest=message_request_payload
            )

    def _validate_response(
        self,
        result: dict,
        aws_number: str,
    ) -> None:
        # documentation of possible delivery statuses from Pinpoint can be found here:
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/pinpoint.html#Pinpoint.Client.send_messages
        delivery_status = result['DeliveryStatus']
        if delivery_status != 'SUCCESSFUL':
            self.statsd_client.incr(f'clients.pinpoint.delivery-status.{delivery_status.lower()}')

            error_message = f'StatusCode: {result["StatusCode"]}, StatusMessage:{result["StatusMessage"]}'

            if delivery_status in self._non_retryable_v1_request_statuses:
                self.statsd_client.incr(f'{SMS_TYPE}.{PINPOINT_PROVIDER}_request.{STATSD_FAILURE}.{aws_number}')
                # indicates 'From' number doesn't exist for this Pinpoint account
                if 'provided number does not exist' in result['StatusMessage']:
                    raise InvalidProviderException(error_message)

                raise NonRetryableException(error_message)
            elif delivery_status in self._retryable_v1_request_statuses:
                self.statsd_client.incr(f'{SMS_TYPE}.{PINPOINT_PROVIDER}_request.{STATSD_RETRYABLE}.{aws_number}')
                if delivery_status == 'UNKNOWN_FAILURE':
                    # Retryable, but we log as an error/exception so it can be fixed, since this is unexpected
                    self.logger.error('Unexpected pinpoint sms request fail for sender: %s | %s', aws_number, result)
                    raise AwsPinpointException(error_message)
                else:
                    raise RetryableException(error_message)

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

        Checks for opt out or buffered and then maps status and status reason.

        Args:
            event_type (str): AWS event type
            record_status (str): Mapping of record status to notification status

        Returns:
            Tuple[str, str]: status and status_reason
        """
        if event_type == '_SMS.OPTOUT':
            status = NOTIFICATION_PERMANENT_FAILURE
            status_reason = STATUS_REASON_BLOCKED
        elif event_type == '_SMS.BUFFERED':
            status = NOTIFICATION_SENDING
            status_reason = None
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

        if delivery_status_message.get('attributes', {}).get('destination_phone_number'):
            # Replace the last 4 charactes with X. Works with empty strings
            delivery_status_message['attributes']['destination_phone_number'] = (
                f'{delivery_status_message["attributes"]["destination_phone_number"][:-4]}XXXX'
            )
        self.logger.info('Translate raw delivery status pinpoint: %s', delivery_status_message)

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
