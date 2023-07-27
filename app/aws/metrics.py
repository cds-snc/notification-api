from __future__ import annotations  # PEP 563 -- Postponed Evaluation of Annotations

from typing import TYPE_CHECKING, Optional

from botocore.exceptions import ClientError
from flask import current_app

if TYPE_CHECKING:  # A special Python 3 constant that is assumed to be True by 3rd party static type checkers
    from app.aws.metrics_logger import MetricsLogger
    from app.queue import RedisQueue


def put_batch_saving_metric(metrics_logger: MetricsLogger, queue: RedisQueue, count: int):
    """
    Metric to calculate how many items are put in an INBOX

    Args:
        queue (RedisQueue): Implementation of queue.RedisQueue for BatchSaving
        count (int): count of an item added to the INBOX.
        metrics (MetricsLogger): Submit metric to cloudwatch
    """
    if metrics_logger.metrics_config.disable_metric_extraction:
        return
    try:
        metrics_logger.set_namespace("NotificationCanadaCa")
        metrics_logger.put_metric("batch_saving_published", count, "Count")
        metrics_logger.set_dimensions({"list_name": queue._inbox})
        metrics_logger.flush()
    except ClientError as e:
        message = "Error sending CloudWatch Metric: {}".format(e)
        current_app.logger.warning(message)
    return


def put_batch_saving_inflight_metric(metrics_logger: MetricsLogger, queue: RedisQueue, count: int):
    """
    Metric to calculate how many inflight lists have been created

    Args:
        count (int): count of an inflight list created.
        metrics (MetricsLogger): Submit metric to cloudwatch
    """
    if metrics_logger.metrics_config.disable_metric_extraction:
        return
    try:
        metrics_logger.set_namespace("NotificationCanadaCa")
        metrics_logger.put_metric("batch_saving_inflight", count, "Count")
        metrics_logger.set_dimensions({"created": "True", "notification_type": queue._suffix, "priority": queue._process_type})
        metrics_logger.flush()
    except ClientError as e:
        message = "Error sending CloudWatch Metric: {}".format(e)
        current_app.logger.warning(message)
    return


def put_batch_saving_inflight_processed(metrics_logger: MetricsLogger, queue: RedisQueue, count: int):
    """
    Metric to calculate how many inflight lists have been processed.

    Args:
        count (int): count of an inflight list created.
        metrics (MetricsLogger): Submit metric to cloudwatch
    """
    if metrics_logger.metrics_config.disable_metric_extraction:
        return
    try:
        metrics_logger.set_namespace("NotificationCanadaCa")
        metrics_logger.put_metric("batch_saving_inflight", count, "Count")
        metrics_logger.set_dimensions(
            {"acknowledged": "True", "notification_type": queue._suffix, "priority": queue._process_type}
        )
        metrics_logger.flush()
    except ClientError as e:
        message = "Error sending CloudWatch Metric: {}".format(e)
        current_app.logger.warning(message)
    return


def put_batch_saving_expiry_metric(metrics_logger: MetricsLogger, queue: RedisQueue, count: int):
    """
    Metric to calculate how many inflight list have not been processed and instead
    sent back to the inbox.

    Args:
        count (int): Number of inflight lists sent to inbox
        metrics (MetricsLogger): Submit metric to cloudwatch
    """
    if metrics_logger.metrics_config.disable_metric_extraction:
        return
    try:
        metrics_logger.set_namespace("NotificationCanadaCa")
        metrics_logger.put_metric("batch_saving_inflight", count, "Count")
        metrics_logger.set_dimensions({"expired": "True", "notification_type": queue._suffix, "priority": queue._process_type})
        metrics_logger.flush()
        metrics_logger.put_metric("batch_saving_inflight", count, "Count")
        metrics_logger.set_dimensions({"expired": "True", "notification_type": "any", "priority": "any"})
        metrics_logger.flush()
    except ClientError as e:
        message = "Error sending CloudWatch Metric: {}".format(e)
        current_app.logger.warning(message)
    return


def put_batch_saving_bulk_created(
    metrics_logger: MetricsLogger, count: int, notification_type: Optional[str] = None, priority: Optional[str] = None
):
    """
    Metric to calculate how many notifications are sent through
    the bulk api

    Args:
        count (int): Number of bulk job batches created
        metrics (MetricsLogger): Submit metric to cloudwatch
        type: priority and notification type
    """
    if metrics_logger.metrics_config.disable_metric_extraction:
        return
    try:
        metrics_logger.set_namespace("NotificationCanadaCa")
        metrics_logger.put_metric("batch_saving_bulk", count, "Count")
        if notification_type is None or priority is None:
            current_app.logger.warning("either notification_type or priority is None")
            metrics_logger.set_dimensions({"created": "True"})
        else:
            metrics_logger.set_dimensions({"created": "True", "notification_type": notification_type, "priority": priority})
        metrics_logger.flush()
    except ClientError as e:
        message = "Error sending CloudWatch Metric: {}".format(e)
        current_app.logger.warning(message)
    return


def put_batch_saving_bulk_processed(
    metrics_logger: MetricsLogger, count: int, notification_type: Optional[str] = None, priority: Optional[str] = None
):
    """
    Metric to calculate how many bulk insertion have been processed.

    Args:
        count (int): Number of bulk job batches processed
        metrics (MetricsLogger): Submit metric to cloudwatch
        type: priority and notification type
    """
    if metrics_logger.metrics_config.disable_metric_extraction:
        return
    try:
        metrics_logger.set_namespace("NotificationCanadaCa")
        metrics_logger.put_metric("batch_saving_bulk", count, "Count")
        if notification_type is None or priority is None:
            current_app.logger.warning("either notification_type or priority is None")
            metrics_logger.set_dimensions({"acknowledged": "True"})
        else:
            metrics_logger.set_dimensions({"acknowledged": "True", "notification_type": notification_type, "priority": priority})
        metrics_logger.flush()
    except ClientError as e:
        message = "Error sending CloudWatch Metric: {}".format(e)
        current_app.logger.warning(message)
    return
