
from unittest import mock
metrics_logger_mock = mock.patch("aws_embedded_metrics.logger.metrics_logger_factory.create_metrics_logger").start()
metric_scope_mock = mock.patch("app.aws.metrics.metric_scope").start()

# metrics_logger_mock = mock.patch("aws_embedded_metrics.logger").start()
from app.aws.metrics import put_batch_saving_metric


def test_put_batch_metric(mocker):
    redis_queue = mocker.MagicMock()
    # metrics_logger_mock = mock.patch("aws_embedded_metrics.logger.metrics_logger.MetricsLogger").start()
    # metrics_logger_mock = mocker.patch("aws_embedded_metrics.logger")
    redis_queue._inbox = "foo"
    redis_queue._expire_inflight_after_seconds = 100
    put_batch_saving_metric(redis_queue)
    import pdb; pdb.set_trace()
    # print(metric_scope_mock.mock_calls)
    metrics_logger_mock.set_dimensions().assert_called_with({"inbox": "foo"})
    metrics_logger_mock.put_metric().assert_called_with("published", 1, "Count")
