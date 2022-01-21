import pytest
from pytest_mock_resources import RedisConfig, create_redis_fixture

from app.queue import MockQueue, generate_notification, generate_notifications


@pytest.fixture(scope="session")
def pmr_redis_config():
    return RedisConfig(image="redis:6.2")


redis = create_redis_fixture()


class TestRedisQueue:
    def test_pytest_mock_redis(self, redis):
        colorSet = "Colors"
        redis.sadd(colorSet, "Red")
        redis.sadd(colorSet, "Orange")
        redis.sadd(colorSet, "Yellow")
        redis.sadd(colorSet, "Green")
        redis.sadd(colorSet, "Blue")
        redis.sadd(colorSet, "Indigo")
        redis.sadd(colorSet, "violet")

        print("Cardinality of the Redis set:")
        print(redis.scard(colorSet))
        print("Contents of the Redis set:")
        print(redis.smembers(colorSet))

    def test_polling_messages_from_queue(self, redis):
        pass

    def test_put_mesages_on_queue(self, redis):
        pass

    def test_acknowledged_messages(self, redis):
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
