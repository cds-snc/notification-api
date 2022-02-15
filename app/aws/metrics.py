from aws_embedded_metrics import metric_scope
from aws_embedded_metrics.config import get_config
from botocore.exceptions import ClientError
from flask import current_app

from app.config import Config
from app.queue import RedisQueue

Metrics_Config = get_config()
Metrics_Config.agent_endpoint = Config.CLOUDWATCH_AGENT_ENDPOINT
Metrics_Config.service_name = "BatchSaving"
Metrics_Config.service_type = "Redis"
Metrics_Config.log_group_name = "BatchSaving"


@metric_scope
def put_batch_saving_metric(queue: RedisQueue, metrics):
    import pdb; pdb.set_trace()
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
