from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Attr
from flask import current_app
from sqlalchemy.orm.exc import NoResultFound

from app.constants import SMS_TYPE
from app.dao.service_sms_sender_dao import dao_get_service_sms_sender_by_id
from app.models import (
    Service,
    Template,
)
from app.notifications.send_notifications import send_notification_bypass_route
from app.va.identifier import IdentifierType


class CompPenMsgHelper:
    dynamodb_table = None

    def __init__(self, dynamodb_table_name: str) -> None:
        """
        This class is a collection of helper methods to facilitate the delivery of schedule Comp and Pen notifications.

        :param dynamodb_table_name (str): the name of the dynamodb table for the db operations, required
        """
        self.dynamodb_table_name = dynamodb_table_name

    def _connect_to_dynamodb(self, dynamodb_table_name: str = None) -> None:
        """Establishes a connection to the dynamodb table with the given name.

        :param dynamodb_table_name (str): the name of the dynamodb table to establish a connection with

        Raises:
            ClientError: if it has trouble connectingto the dynamodb
        """
        if dynamodb_table_name is None:
            dynamodb_table_name = self.dynamodb_table_name

        # connect to dynamodb table
        dynamodb_resource = boto3.resource('dynamodb')
        self.dynamodb_table = dynamodb_resource.Table(dynamodb_table_name)

    def get_dynamodb_comp_pen_messages(
        self,
        message_limit: int,
    ) -> list:
        """
        Helper function to get the Comp and Pen data from our dynamodb cache table.

        Items should be returned if all of these attribute conditions are met:
            1) item exists on the `is-processed-index`
            2) paymentAmount exists

        :param message_limit: the number of rows to search at a time and the max number of items that should be returned
        :return: a list of entries from the table that have not been processed yet

        https://boto3.amazonaws.com/v1/documentation/api/latest/guide/dynamodb.html#querying-and-scanning
        """

        if self.dynamodb_table is None:
            self._connect_to_dynamodb()

        is_processed_index = 'is-processed-index'

        filters = Attr('paymentAmount').exists()

        results = self.dynamodb_table.scan(FilterExpression=filters, Limit=message_limit, IndexName=is_processed_index)
        items: list = results.get('Items')

        if items is None:
            items = []
            current_app.logger.critical(
                'Error in get_dynamodb_comp_pen_messages trying to read "Items" from dynamodb table scan result. '
                'Returned results does not include "Items" - results: %s',
                results,
            )

        # Keep getting items from the table until we have the number we want to send, or run out of items
        while 'LastEvaluatedKey' in results and len(items) < message_limit:
            results = self.dynamodb_table.scan(
                FilterExpression=filters,
                Limit=message_limit,
                IndexName=is_processed_index,
                ExclusiveStartKey=results['LastEvaluatedKey'],
            )

            items.extend(results['Items'])

        return items[:message_limit]

    def remove_dynamo_item_is_processed(self, comp_and_pen_messages: list) -> None:
        """
        Remove the 'is_processed' key from each item in the provided list and update the entries in the DynamoDB table.

        :param comp_and_pen_messages (list): A list of dictionaries, where each dictionary contains the data for an item
            to be updated in the DynamoDB table. Each dictionary should at least contain 'participant_id' and
            'payment_id' keys, as well as the 'is_processed' key to be removed.

        Raises:
            Exception: If an error occurs during the update of any item in the DynamoDB table, the exception is logged
                    with critical severity, and then re-raised.
        """
        if self.dynamodb_table is None:
            self._connect_to_dynamodb()

        # send messages and update entries in dynamodb table
        with self.dynamodb_table.batch_writer() as batch:
            for item in comp_and_pen_messages:
                participant_id = item.get('participant_id')

                item.pop('is_processed', None)

                # update dynamodb entries
                try:
                    batch.put_item(Item=item)
                    current_app.logger.debug(
                        'updated record from dynamodb ("is_processed" should no longer exist): %s', item
                    )
                except Exception as e:
                    current_app.logger.critical('Failed to update the record from dynamodb: %s', participant_id)
                    current_app.logger.exception(e)

        current_app.logger.info('Comp and Pen - Successfully updated dynamodb entries - removed "is_processed" field')

    def send_comp_and_pen_sms(
        self,
        service: Service,
        template: Template,
        sms_sender_id: str,
        comp_and_pen_messages: list[dict],
        perf_to_number: str,
    ) -> None:
        """
        Sends scheduled SMS notifications to recipients based on the provided parameters.

        Args:
            :param service (Service): The service used to send the SMS notifications.
            :param template (Template): The template used for the SMS notifications.
            :param sms_sender_id (str): The ID of the SMS sender.
            :param comp_and_pen_messages (list[dict]): A list of dictionaries from the dynamodb table containing the
                details needed to send the messages.
            :param perf_to_number (str): The recipient's phone number.

        Raises:
            Exception: If there is an error while sending the SMS notification.
        """
        try:
            reply_to_text = dao_get_service_sms_sender_by_id(service.id, sms_sender_id).sms_sender
        except (NoResultFound, AttributeError):
            current_app.logger.exception('Unable to send comp and pen notifications due to improper sms_sender')
            raise

        for item in comp_and_pen_messages:
            vaprofile_id = str(item.get('vaprofile_id'))
            participant_id = item.get('participant_id')
            # Format payment amount as str with appropriate commas
            payment_amount = f'{item.get("paymentAmount", 0):0,.2f}'

            current_app.logger.debug('sending - record from dynamodb: %s', participant_id)

            # Use perf_to_number as the recipient if available. Otherwise, use vaprofile_id as recipient_item.
            recipient = perf_to_number
            recipient_item = (
                None
                if perf_to_number is not None
                else {
                    'id_type': IdentifierType.VA_PROFILE_ID.value,
                    'id_value': vaprofile_id,
                }
            )

            try:
                # call generic method to send messages
                send_notification_bypass_route(
                    service=service,
                    template=template,
                    notification_type=SMS_TYPE,
                    reply_to_text=reply_to_text,
                    personalisation={'amount': payment_amount},
                    sms_sender_id=sms_sender_id,
                    recipient=recipient,
                    recipient_item=recipient_item,
                    notification_id=uuid4(),
                )
            except Exception as e:
                current_app.logger.critical(
                    'Error attempting to send Comp and Pen notification with '
                    'send_comp_and_pen_sms | record from dynamodb: %s',
                    participant_id,
                )
                current_app.logger.exception(e)
            else:
                if perf_to_number is not None:
                    current_app.logger.info(
                        'Notification sent using Perf simulated number %s instead of vaprofile_id', perf_to_number
                    )

                current_app.logger.info('Notification sent to queue for record from dynamodb: %s', participant_id)
