from flask import current_app
from notifications_utils.statsd_decorators import statsd

from app import notify_celery
from app.feature_flags import FeatureFlag, is_feature_enabled


@notify_celery.task(bind=True, name="process-pinpoint-inbound-sms", max_retries=5, default_retry_delay=300)
@statsd(namespace="tasks")
def process_pinpoint_inbound_sms(self, event):
    if not is_feature_enabled(FeatureFlag.PINPOINT_INBOUND_SMS_ENABLED):
        current_app.logger.info('Pinpoint inbound SMS toggle is disabled, skipping task')
        return True
