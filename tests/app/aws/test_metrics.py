

from app.aws.metrics import put_batch_saving_metric

def test_put_batch_metric(mocker):
    metric_scope_mock = mocker.patch("app.aws.metrics.metric_scope")
    redis_queue = mocker.MagicMock()
    redis_queue._inbox = "foo"
    redis_queue._expire_inflight_after_seconds = 100
    put_batch_saving_metric(redis_queue)
    metric_scope_mock.set_dimensions().assert_called_with({"inbox": "foo"})
    metric_scope_mock.put_metric().assert_called_with("published", 1, "Count")