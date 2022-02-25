from os import environ
from unittest.mock import patch
from uuid import uuid4

from aws_embedded_metrics.config import get_config  # type: ignore
from aws_embedded_metrics.environment.ec2_environment import (  # type: ignore
    EC2Environment,
)
from aws_embedded_metrics.environment.lambda_environment import (  # type: ignore
    LambdaEnvironment,
)

from app.aws.metrics_logger import MetricsLogger


class TestMetricsLogger:
    def test_environment_defaults_to_ec2(self):
        metrics_config = get_config()
        metrics_config.environment = ""
        metrics_logger = MetricsLogger()
        assert type(metrics_logger.environment) is EC2Environment

    @patch.dict(environ, {"AWS_EXECUTION_ENV": "foo"}, clear=True)
    def test_environment_set_lambda_when_lambda_envs_exist(self):
        metrics_logger = MetricsLogger()
        assert type(metrics_logger.environment) is LambdaEnvironment

    def test_environment_changes_when_set(self):
        metrics_config = get_config()
        metrics_config.environment = "lambda"
        metrics_logger = MetricsLogger()
        assert type(metrics_logger.environment) is LambdaEnvironment

    def test_flush_writes_to_stdout(self, capsys):
        metrics_config = get_config()
        metrics_config.environment = "local"
        metrics_logger = MetricsLogger()
        metric_name = f"foo_bar_baz_{str(uuid4())}"
        metrics_logger.put_metric(metric_name, 1, "Count")
        metrics_logger.flush()
        captured = capsys.readouterr()
        assert metric_name in str(captured.out)
