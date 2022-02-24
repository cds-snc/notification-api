import pytest
from botocore.exceptions import ClientError
from flask import Flask

from app import create_app
from app.aws.metrics import (
    put_batch_saving_expiry_metric,
    put_batch_saving_inflight_metric,
    put_batch_saving_inflight_processed,
    put_batch_saving_metric,
)
from app.config import Config, Test


class TestBatchSavingMetricsFunctions:
    @pytest.fixture(autouse=True)
    def app(self):
        config: Config = Test()
        config.REDIS_ENABLED = True
        app = Flask(config.NOTIFY_ENVIRONMENT)
        create_app(app, config)
        ctx = app.app_context()
        ctx.push()
        with app.test_request_context():
            yield app
        ctx.pop()
        return app

    def test_put_batch_metric(self, mocker):
        redis_queue = mocker.MagicMock()
        metrics_logger_mock = mocker.patch("app.aws.metrics_logger")
        redis_queue._inbox = "foo"

        put_batch_saving_metric(metrics_logger_mock, redis_queue, 1)
        metrics_logger_mock.set_dimensions.assert_called_with({"list_name": "foo"})
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_published", 1, "Count")

    def test_put_batch_metric_multiple_items(self, mocker):
        redis_queue = mocker.MagicMock()
        metrics_logger_mock = mocker.patch("app.aws.metrics_logger")
        redis_queue._inbox = "foo"

        put_batch_saving_metric(metrics_logger_mock, redis_queue, 20)
        metrics_logger_mock.set_dimensions.assert_called_with({"list_name": "foo"})
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_published", 20, "Count")

    def test_put_batch_saving_in_flight_metric(self, mocker):
        metrics_logger_mock = mocker.MagicMock()

        put_batch_saving_inflight_metric(metrics_logger_mock, 1)
        metrics_logger_mock.set_dimensions.assert_called_with({"created": "True"})
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_inflight", 1, "Count")

    def test_put_batch_saving_inflight_processed(self, mocker):
        metrics_logger_mock = mocker.patch("app.aws.metrics_logger")

        put_batch_saving_inflight_processed(metrics_logger_mock, 1)
        metrics_logger_mock.set_dimensions.assert_called_with({"acknowledged": "True"})
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_inflight", 1, "Count")

    def test_put_batch_saving_expiry_metric(self, mocker):
        metrics_logger_mock = mocker.patch("app.aws.metrics_logger")

        put_batch_saving_expiry_metric(metrics_logger_mock, 1)
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_inflight", 1, "Count")
        metrics_logger_mock.set_dimensions.assert_called_with({"expired": "True"})

    def test_put_batch_metric_unknown_error(self, app, mocker):
        redis_queue = mocker.MagicMock()
        metrics_logger_mock = mocker.patch("app.aws.metrics_logger")
        mock_logger = mocker.patch("app.aws.metrics.current_app.logger.warning")
        redis_queue._inbox = "foo"

        metrics_logger_mock.flush.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "Not Found"}}, "bar"
        )

        put_batch_saving_metric(metrics_logger_mock, redis_queue, 1)
        mock_logger.assert_called_with(
            "Error sending CloudWatch Metric: An error occurred (ResourceNotFoundException) when calling the bar operation: Not Found"
        )
