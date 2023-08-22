from unittest.mock import call

import pytest
from botocore.exceptions import ClientError
from flask import Flask

from app import create_app
from app.aws.metrics import (
    put_batch_saving_bulk_created,
    put_batch_saving_bulk_processed,
    put_batch_saving_expiry_metric,
    put_batch_saving_inflight_metric,
    put_batch_saving_inflight_processed,
    put_batch_saving_metric,
)
from app.config import Config, Test


class TestBatchSavingMetricsFunctions:
    @pytest.fixture(autouse=True)
    def app(self):
        config: Config = Test() # type: ignore
        config.REDIS_ENABLED = True
        app = Flask(config.NOTIFY_ENVIRONMENT)
        create_app(app, config)
        ctx = app.app_context()
        ctx.push()
        with app.test_request_context():
            yield app
        ctx.pop()
        return app

    @pytest.fixture(autouse=True)
    def metrics_logger_mock(self, mocker):
        metrics_logger_mock = mocker.patch("app.aws.metrics_logger")
        metrics_logger_mock.metrics_config.disable_metric_extraction = False
        return metrics_logger_mock

    def test_put_batch_metric(self, mocker, metrics_logger_mock):
        redis_queue = mocker.MagicMock()
        redis_queue._inbox = "foo"
        put_batch_saving_metric(metrics_logger_mock, redis_queue, 1)
        metrics_logger_mock.set_dimensions.assert_called_with({"list_name": "foo"})
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_published", 1, "Count")
        assert metrics_logger_mock.set_dimensions.called, "set_dimensions was not called and should have been"

    def test_put_batch_metric_disabled(self, mocker, metrics_logger_mock):
        redis_queue = mocker.MagicMock()
        redis_queue._inbox = "foo"
        metrics_logger_mock.metrics_config.disable_metric_extraction = True
        put_batch_saving_metric(metrics_logger_mock, redis_queue, 1)
        assert not metrics_logger_mock.set_dimensions.called, "set_dimensions was called and should not have been"
        assert not metrics_logger_mock.put_metric.called, "put_metric was called and should not have been"

    def test_put_batch_metric_multiple_items(self, mocker, metrics_logger_mock):
        redis_queue = mocker.MagicMock()
        redis_queue._inbox = "foo"

        put_batch_saving_metric(metrics_logger_mock, redis_queue, 20)
        metrics_logger_mock.set_dimensions.assert_called_with({"list_name": "foo"})
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_published", 20, "Count")

    def test_put_batch_saving_in_flight_metric(self, mocker, metrics_logger_mock):
        redis_queue = mocker.MagicMock()
        redis_queue._suffix = "foo"
        redis_queue._process_type = "bar"
        put_batch_saving_inflight_metric(metrics_logger_mock, redis_queue, 1)
        metrics_logger_mock.set_dimensions.assert_called_with({"created": "True", "notification_type": "foo", "priority": "bar"})
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_inflight", 1, "Count")

    def test_put_batch_saving_inflight_processed(self, mocker, metrics_logger_mock):
        redis_queue = mocker.MagicMock()
        redis_queue._suffix = "foo"
        redis_queue._process_type = "bar"
        put_batch_saving_inflight_processed(metrics_logger_mock, redis_queue, 1)
        metrics_logger_mock.set_dimensions.assert_called_with(
            {"acknowledged": "True", "notification_type": "foo", "priority": "bar"}
        )
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_inflight", 1, "Count")

    def test_put_batch_saving_expiry_metric(self, mocker, metrics_logger_mock):
        redis_queue = mocker.MagicMock()
        redis_queue._suffix = "foo"
        redis_queue._process_type = "bar"
        put_batch_saving_expiry_metric(metrics_logger_mock, redis_queue, 1)
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_inflight", 1, "Count")
        metrics_logger_mock.set_dimensions.assert_has_calls(
            [
                call({"expired": "True", "notification_type": "foo", "priority": "bar"}),
                call({"expired": "True", "notification_type": "any", "priority": "any"}),
            ]
        )

    def test_put_batch_saving_bulk_created(self, mocker, metrics_logger_mock):
        put_batch_saving_bulk_created(metrics_logger_mock, 1, "foo", "bar")
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_bulk", 1, "Count")
        metrics_logger_mock.set_dimensions.assert_called_with({"created": "True", "notification_type": "foo", "priority": "bar"})

    def test_put_batch_saving_bulk_processed(self, mocker, metrics_logger_mock):
        put_batch_saving_bulk_processed(metrics_logger_mock, 1, notification_type="foo", priority="bar")
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_bulk", 1, "Count")
        metrics_logger_mock.set_dimensions.assert_called_with(
            {"acknowledged": "True", "notification_type": "foo", "priority": "bar"}
        )

    def test_put_batch_metric_unknown_error(self, mocker, metrics_logger_mock):
        redis_queue = mocker.MagicMock()
        mock_logger = mocker.patch("app.aws.metrics.current_app.logger.warning")
        redis_queue._inbox = "foo"

        metrics_logger_mock.flush.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "Not Found"}}, "bar"
        )

        put_batch_saving_metric(metrics_logger_mock, redis_queue, 1)
        mock_logger.assert_called_with(
            "Error sending CloudWatch Metric: An error occurred (ResourceNotFoundException) when calling the bar operation: Not Found"
        )
