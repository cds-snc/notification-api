from flask import current_app
from app import notify_celery

@notify_celery.task(bind=True, name="process-delivery-status-result", max_retries=48, default_retry_delay=300)
def process_delivery_status(self, event: CeleryEvent) -> bool:
    logger.info('processing delivery status: %s', event)
    return True