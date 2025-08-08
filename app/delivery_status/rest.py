import base64
import json
import time

from flask import Blueprint, current_app, jsonify, request

from app import aws_pinpoint_client
from app.celery.exceptions import NonRetryableException
from app.celery.process_delivery_status_result_tasks import get_notification_platform_status
from app.celery.process_pinpoint_v2_receipt_tasks import process_pinpoint_v2_receipt_results
from app.clients.sms import SmsStatusRecord
from app.config import QueueNames
from app.errors import register_errors

pinpoint_v2_blueprint = Blueprint('pinpoint_v2', __name__)
register_errors(pinpoint_v2_blueprint)


@pinpoint_v2_blueprint.route('/delivery-status/sms/pinpointv2', methods=['POST'])
def handler():
    """
    Handle Pinpoint SMS Voice V2 delivery status updates.
    Decodes request body and processes each record through Celery.

    Returns:
        tuple: JSON response body and HTTP status code 200.
    """
    request_data = request.get_json()

    current_app.logger.debug('PinpointV2 delivery-status request: %s', request_data)

    records = request_data.get('records', [])

    for record in records:
        try:
            # TODO #1832 - Handle sending 400 if Firehose need to retry
            data = record.get('data')
            decoded_record_data = json.loads(base64.b64decode(data).decode('utf-8'))
        except (KeyError, ValueError, json.JSONDecodeError, Exception) as e:
            current_app.logger.error(
                'Failed to decode PinpointV2 delivery-status record data: %s | Error: %s', record, str(e)
            )
            continue

        current_app.logger.debug('PinpointV2 decoded PinpointV2 delivery-status record data: %s', decoded_record_data)

        try:
            notification_platform_status: SmsStatusRecord = get_notification_platform_status(
                aws_pinpoint_client, decoded_record_data
            )
        except NonRetryableException as e:
            current_app.logger.error(
                'Validation for PinpointV2 delivery-status records failed: %s | Error: %s',
                decoded_record_data.get('messageId', 'unknown messageId'),
                str(e),
            )
            continue

        process_pinpoint_v2_receipt_results.apply_async(
            [notification_platform_status, decoded_record_data.get('eventTimestamp')],
            queue=QueueNames.NOTIFY,
            serializer='pickle',
        )

    return jsonify(
        {
            'requestId': request_data.get('requestId'),
            'timestamp': str(int(time.time() * 1000)),
        }
    ), 200
