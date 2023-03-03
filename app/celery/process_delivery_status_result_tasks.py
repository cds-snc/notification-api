from flask import current_app
from app import notify_celery
import base64
import json

# Create SQS Queue for Process Deliver Status.
@notify_celery.task(bind=True, name="process-delivery-status-result", max_retries=48, default_retry_delay=300)
def process_delivery_status(self, event) -> bool:
    current_app.logger.info('processing delivery status: %s', event)

    try:
        delivery_receipt_message = json.loads(base64.b64decode(event['Message']))
        current_app.logger.info('processing delivery status: %s', delivery_receipt_message)
    except (json.decoder.JSONDecodeError, ValueError, TypeError, KeyError) as e:
        current_app.logger.exception(e)
        return None
    
    return True
