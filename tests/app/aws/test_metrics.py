from unittest import mock

metric_scope_mock = mock.patch("app.aws.metrics.metric_scope").start()
from app.aws.metrics import put_batch_saving_metric


def test_put_batch_metric(mocker):
    redis_queue = mocker.MagicMock()
    metrics_logger_mock = mocker.MagicMock()
    redis_queue._inbox = "foo"
    redis_queue._expire_inflight_after_seconds = 100
    put_batch_saving_metric.__wrapped__(redis_queue, metrics_logger_mock)
    metrics_logger_mock.set_dimensions.assert_called_with({"inbox": "foo"})
    metrics_logger_mock.put_metric.assert_called_with("published", 1, "Count")
    metrics_logger_mock.set_property.assert_called_with("expiry", 100)
