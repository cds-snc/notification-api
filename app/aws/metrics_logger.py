from os import environ

from aws_embedded_metrics import MetricsLogger as _MetricsLogger  # type: ignore
from aws_embedded_metrics.config import get_config  # type: ignore
from aws_embedded_metrics.environment.ec2_environment import (  # type: ignore
    EC2Environment,
)
from aws_embedded_metrics.environment.lambda_environment import (  # type: ignore
    LambdaEnvironment,
)
from aws_embedded_metrics.environment.local_environment import (  # type: ignore
    LocalEnvironment,
)

from app.config import Config


class MetricsLogger(_MetricsLogger):
    def __init__(self):
        super().__init__(None, None)
        metrics_config = get_config()
        metrics_config.agent_endpoint = Config.CLOUDWATCH_AGENT_ENDPOINT
        metrics_config.service_name = "BatchSaving"
        metrics_config.service_type = "Redis"
        metrics_config.log_group_name = "BatchSaving"

        if "AWS_EXECUTION_ENV" in environ:
            metrics_config.environment = "lambda"

        if not Config.STATSD_ENABLED:
            metrics_config.disable_metric_extraction = True

        lower_configured_enviroment = metrics_config.environment.lower()
        if lower_configured_enviroment == "local":
            self.environment = LocalEnvironment()
        elif lower_configured_enviroment == "lambda":
            self.environment = LambdaEnvironment()
        else:
            self.environment = EC2Environment()

    def flush(self) -> None:
        """Override the default async MetricsLogger.flush method, flushing to stdout immediately"""
        sink = self.environment.get_sink()
        sink.accept(self.context)  # type: ignore
        self.context = self.context.create_copy_with_context()  # type: ignore
