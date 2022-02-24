from __future__ import annotations  # PEP 563 -- Postponed Evaluation of Annotations

from typing import TYPE_CHECKING

from aws_embedded_metrics.config import get_config  # type: ignore
from botocore.exceptions import ClientError
from flask import current_app

from app.config import Config

if TYPE_CHECKING:  # A special Python 3 constant that is assumed to be True by 3rd party static type checkers
    from app.aws.metrics_logger import MetricsLogger
    from app.queue import RedisQueue

metrics_config = get_config()
metrics_config.agent_endpoint = Config.CLOUDWATCH_AGENT_ENDPOINT
metrics_config.service_name = "BatchSaving"
metrics_config.service_type = "Redis"
metrics_config.log_group_name = "BatchSaving"

if not Config.STATSD_ENABLED:
    metrics_config.disable_metric_extraction = True


def put_batch_saving_metric(metrics_logger: MetricsLogger, queue: RedisQueue, count: int):
    """
    Metric to calculate how many items are put in an INBOX

    Args:
        queue (RedisQueue): Implementation of queue.RedisQueue for BatchSaving
        count (int): default: 1, count of an item added to the INBOX.
        metrics (MetricsLogger): Submit metric to cloudwatch
    """
    if metrics_config.disable_metric_extraction:
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


def put_batch_saving_inflight_metric(metrics_logger: MetricsLogger, count: int):
    """
    Metric to calculate how many inflight lists have been created

    Args:
        count (int): default: 1, count of an inflight list created.
        metrics (MetricsLogger): Submit metric to cloudwatch
    """
    if metrics_config.disable_metric_extraction:
        return
    try:
        metrics_logger.set_namespace("NotificationCanadaCa")
        metrics_logger.put_metric("batch_saving_inflight", count, "Count")
        metrics_logger.set_dimensions({"created": "True"})
        metrics_logger.flush()
    except ClientError as e:
        message = "Error sending CloudWatch Metric: {}".format(e)
        current_app.logger.warning(message)
    return


def put_batch_saving_inflight_processed(metrics_logger: MetricsLogger, count: int):
    """
    Metric to calculate how many inflight lists have been processed.

    Args:
        count (int): default: 1, count of an inflight list created.
        metrics (MetricsLogger): Submit metric to cloudwatch
    """
    if metrics_config.disable_metric_extraction:
        return
    try:
        metrics_logger.set_namespace("NotificationCanadaCa")
        metrics_logger.put_metric("batch_saving_inflight", count, "Count")
        metrics_logger.set_dimensions({"acknowledged": "True"})
        metrics_logger.flush()
    except ClientError as e:
        message = "Error sending CloudWatch Metric: {}".format(e)
        current_app.logger.warning(message)
    return


def put_batch_saving_expiry_metric(metrics_logger, count: int):
    """
    Metric to calculate how many inflight list have not been processed and instead
    sent back to the inbox.

    Args:
        count (int): Number of inlfight lists sent to inbox
        metrics (MetricsLogger): Submit metric to cloudwatch
    """
    if metrics_config.disable_metric_extraction:
        return
    try:
        metrics_logger.set_namespace("NotificationCanadaCa")
        metrics_logger.put_metric("batch_saving_inflight", count, "Count")
        metrics_logger.set_dimensions({"expired": "True"})
        metrics_logger.flush()
    except ClientError as e:
        message = "Error sending CloudWatch Metric: {}".format(e)
        current_app.logger.warning(message)
    return
