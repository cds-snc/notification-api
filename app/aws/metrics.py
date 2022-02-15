from aws_embedded_metrics import metric_scope
from aws_embedded_metrics.config import get_config
from botocore.exceptions import ClientError
from flask import current_app

from app.queue import RedisQueue

Config = get_config()
Config.service_name = "BatchSaving"
Config.service_type = "Redis"
Config.log_group_name = "BatchSaving"


@metric_scope
def put_batch_saving_metric(queue: RedisQueue, metrics):
    try:
        metrics.set_namespace("BatchSaving")
        metrics.set_dimensions({"inbox": queue._inbox})
        metrics.put_metric("published", 1, "Count")
        metrics.set_property("expiry", queue._expire_inflight_after_seconds)
    except ClientError as e:
        message = "Error sending CloudWatch Metric: {}".format(e)
        current_app.logger.exception(message)
        pass
    return
