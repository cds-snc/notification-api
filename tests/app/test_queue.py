import pytest
from flask import Flask
from pytest_mock_resources import RedisConfig, create_redis_fixture

from app import create_app, redis_store
from app.queue import Buffer, MockQueue, RedisQueue, generate_notification


@pytest.fixture(scope="session")
def pmr_redis_config():
    return RedisConfig(image="redis:6.2")


redis = create_redis_fixture()


class TestRedisQueue:
    @pytest.fixture(autouse=True)
    def app(self):
        app = Flask("test")
        # app.config["REDIS_URL"] = "redis://host.docker.internal:6380"
        create_app(app)
        ctx = app.app_context()
        ctx.push()
        with app.test_request_context():
            yield app
        ctx.pop()
        return app

    @pytest.fixture()
    def redis_client(self):
        return redis_store.redis_store

    @pytest.fixture()
    def redis_queue(self, redis_client):
        return RedisQueue(redis_client)

    @pytest.fixture()
    def given_filled_inbox(self, redis, redis_queue):
        notification = next(generate_notification())
        redis_queue.publish(notification)
        yield
        redis.delete(Buffer.INBOX.value)

    def test_put_mesages(self, redis, redis_queue):
        notification = next(generate_notification())
        redis_queue.publish(notification)
        assert redis.llen(Buffer.INBOX.value) == 1
        redis.delete(Buffer.INBOX.value)

    def test_polling_message(self, redis, redis_queue, given_filled_inbox):
        (receipt, notifications) = redis_queue.poll(10)
        assert len(notifications) == 1
        assert isinstance(notifications[0], dict)
        assert redis.llen(Buffer.INBOX.value) == 0
        assert redis.llen(redis_queue.get_inflight_name(receipt)) == 1

    def test_polling_many_messages(self, redis, redis_queue, given_filled_inbox):
        pass

    def test_polling_zero_message(self, redis, redis_queue):
        (receipt, notifications) = redis_queue.poll(10)
        assert len(notifications) == 0
        assert redis.llen(Buffer.INBOX.value) == 0
        assert redis.llen(redis_queue.get_inflight_name(receipt)) == 0

    def test_acknowledged_messages(self, redis, redis_queue, given_filled_inbox):
        (receipt, notifications) = redis_queue.poll(10)
        redis_queue.acknowledge(receipt)
        assert len(notifications) > 0
        assert redis.llen(Buffer.INBOX.value) == 0
        assert redis.llen(redis_queue.get_inflight_name(receipt)) == 0
        assert len(redis.keys("*")) == 0

    def test_messages_serialization_after_poll(self, redis, redis_queue, given_filled_inbox):
        pass


@pytest.mark.usefixtures("notify_api")
class TestMockQueue:
    @pytest.fixture
    def mock_queue(self):
        return MockQueue()

    def test_polling_messages_from_queue(self, mock_queue):
        notifications: list = mock_queue.poll(10)
        assert notifications is not None
        assert len(notifications) == 10

    def test_publish_mesages_on_queue(self, mock_queue):
        notification = next(generate_notification())
        mock_queue.publish(notification)

        # This should not add change internal data structure
        # or differ from a random output generation due to the
        # nature of MockQueue.
        notifications = mock_queue.poll(1)
        assert notifications is not None
        assert len(notifications) == 1
        assert notification.service_id != notifications[0].service_id

    def test_acknowledged_messages(self, mock_queue):
        mock_queue.acknowledge([1, 2, 3])
