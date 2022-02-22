from unittest import mock

metric_scope_mock = mock.patch("app.aws.metrics.metric_scope").start()


class TestBatchSavingMetricsFunctions:
    def test_put_batch_metric(self, mocker):
        redis_queue = mocker.MagicMock()
        metrics_logger_mock = mocker.MagicMock()
        redis_queue._inbox = "foo"
        redis_queue._expire_inflight_after_seconds = 100
        from app.aws.metrics import put_batch_saving_metric  # Import after global patch

        put_batch_saving_metric.__wrapped__(redis_queue, 1, metrics_logger_mock)
        metrics_logger_mock.set_dimensions.assert_called_with({"list_name": "foo"})
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_published", 1, "Count")

    def test_put_batch_metric_multiple_items(self, mocker):
        redis_queue = mocker.MagicMock()
        metrics_logger_mock = mocker.MagicMock()
        redis_queue._inbox = "foo"
        redis_queue._expire_inflight_after_seconds = 100
        from app.aws.metrics import put_batch_saving_metric  # Import after global patch

        put_batch_saving_metric.__wrapped__(redis_queue, 20, metrics_logger_mock)
        metrics_logger_mock.set_dimensions.assert_called_with({"list_name": "foo"})
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_published", 20, "Count")

    def test_put_batch_saving_in_flight_metric(self, mocker):
        metrics_logger_mock = mocker.MagicMock()
        from app.aws.metrics import (
            put_batch_saving_in_flight_metric,  # Import after global patch
        )

        put_batch_saving_in_flight_metric.__wrapped__(1, metrics_logger_mock)
        metrics_logger_mock.set_dimensions.assert_called_with({"created": "True"})
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_inflight", 1, "Count")

    def test_put_batch_saving_inflight_processed(self, mocker):
        metrics_logger_mock = mocker.MagicMock()
        from app.aws.metrics import (
            put_batch_saving_inflight_processed,  # Import after global patch
        )

        put_batch_saving_inflight_processed.__wrapped__(1, metrics_logger_mock)
        metrics_logger_mock.set_dimensions.assert_called_with({"acknowledged": "True"})
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_inflight", 1, "Count")

    def test_put_batch_saving_expiry_metric(self, mocker):
        metrics_logger_mock = mocker.MagicMock()
        from app.aws.metrics import (
            put_batch_saving_expiry_metric,  # Import after global patch
        )

        put_batch_saving_expiry_metric.__wrapped__(1, metrics_logger_mock)
        metrics_logger_mock.put_metric.assert_called_with("batch_saving_inflight", 1, "Count")
        metrics_logger_mock.set_dimensions.assert_called_with({"expired": "True"})
