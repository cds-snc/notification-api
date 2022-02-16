from __future__ import annotations  # PEP 563 -- Postponed Evaluation of Annotations

from typing import TYPE_CHECKING

from aws_embedded_metrics import metric_scope  # type: ignore
from aws_embedded_metrics.config import get_config  # type: ignore
from botocore.exceptions import ClientError
from flask import current_app

from app.config import Config

if TYPE_CHECKING:  # A special Python 3 constant that is assumed to be True by 3rd party static type checkers
    from aws_embedded_metrics.logger.metrics_logger import MetricsLogger  # type: ignore

    from app.queue import RedisQueue

Metrics_Config = get_config()
Metrics_Config.agent_endpoint = Config.CLOUDWATCH_AGENT_ENDPOINT
Metrics_Config.service_name = "BatchSaving"
Metrics_Config.service_type = "Redis"
Metrics_Config.log_group_name = "BatchSaving"


@metric_scope
def put_batch_saving_metric(queue: RedisQueue, count: int, metrics: MetricsLogger):
    try:
        metrics.set_namespace("BatchSaving")
        metrics.set_dimensions({"inbox": queue._inbox})
        metrics.put_metric("published", count, "Count")
        metrics.set_property("expiry", queue._expire_inflight_after_seconds)
    except ClientError as e:
        message = "Error sending CloudWatch Metric: {}".format(e)
        current_app.logger.exception(message)
        pass
    return
