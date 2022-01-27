from contextlib import contextmanager

import pytest
from flask import Flask
from pytest_mock_resources import RedisConfig, create_redis_fixture

from app import create_app, redis_store
from app.config import Config, Development
from app.queue import Buffer, MockQueue, RedisQueue, generate_element


@pytest.fixture(scope="session")
def pmr_redis_config():
    return RedisConfig(image="redis:6.2", host="localhost", port="6380", ci_port="6380")


redis = create_redis_fixture(scope="function")
REDIS_ELEMENTS_COUNT = 123


class TestRedisQueue:
    @pytest.fixture(autouse=True)
    def app(self):
        config: Config = Development()
        config.REDIS_ENABLED = True
        app = Flask("test")
        create_app(app, config)
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

    @contextmanager
    def given_inbox_with_one_element(self, redis, redis_queue):
        self.delete_all_list(redis)
        notification = generate_element()
        try:
            redis_queue.publish(notification)
            yield
        finally:
            self.delete_all_list(redis)

    @contextmanager
    def given_inbox_with_many_indexes(self, redis, redis_queue):
        self.delete_all_list(redis)
        try:
            indexes = [str(i) for i in range(0, REDIS_ELEMENTS_COUNT)]
            [redis_queue.publish(index) for index in indexes]
            yield
        finally:
            self.delete_all_list(redis)

    @pytest.mark.serial
    def delete_all_list(self, redis):
        self.delete_all_inbox(redis)
        self.delete_all_inflight(redis)

    @pytest.mark.serial
    def delete_all_inbox(self, redis):
        for key in redis.scan_iter(f"{Buffer.INBOX.value}*"):
            redis.delete(key)

    @pytest.mark.serial
    def delete_all_inflight(self, redis):
        for key in redis.scan_iter(f"{Buffer.IN_FLIGHT.value}*"):
            redis.delete(key)

    @pytest.mark.serial
    def test_put_mesages(self, redis, redis_queue):
        element = generate_element()
        redis_queue.publish(element)
        assert redis.llen(Buffer.INBOX.name()) == 1
        self.delete_all_list(redis)

    @pytest.mark.serial
    def test_polling_message(self, redis, redis_queue):
        with self.given_inbox_with_one_element(redis, redis_queue):
            (receipt, elements) = redis_queue.poll(10)
            assert len(elements) == 1
            assert isinstance(elements[0], str)
            assert redis.llen(Buffer.INBOX.name()) == 0
            assert redis.llen(redis_queue.get_inflight_name(receipt)) == 1

    @pytest.mark.serial
    @pytest.mark.parametrize("count", [0, 1, 98, 99, 100, 101, REDIS_ELEMENTS_COUNT, REDIS_ELEMENTS_COUNT + 1, 500])
    def test_polling_many_messages(self, redis, redis_queue, count):
        with self.given_inbox_with_many_indexes(redis, redis_queue):
            real_count = count if count < REDIS_ELEMENTS_COUNT else REDIS_ELEMENTS_COUNT
            (receipt, elements) = redis_queue.poll(count)
            assert len(elements) == real_count
            if count < REDIS_ELEMENTS_COUNT:
                assert redis.llen(Buffer.INBOX.name()) > 0
            else:
                assert redis.llen(Buffer.INBOX.name()) == 0
            assert redis.llen(redis_queue.get_inflight_name(receipt)) == real_count

    @pytest.mark.serial
    @pytest.mark.parametrize("suffix", ["sms", "email", "🎅", "", None])
    def test_polling_message_with_custom_inbox_name(self, redis, redis_client, suffix):
        self.delete_all_list(redis)
        try:
            redis_queue = RedisQueue(redis_client, suffix)
            element = generate_element()
            redis_queue.publish(element)
            assert redis.llen(Buffer.INBOX.name(suffix)) == 1

            (receipt, elements) = redis_queue.poll(10)
            assert len(elements) == 1
            assert redis.llen(Buffer.INBOX.name(suffix)) == 0
            assert redis.llen(redis_queue.get_inflight_name(receipt)) == 1

            redis_queue.acknowledge(receipt)
            assert redis.llen(Buffer.INBOX.name(suffix)) == 0
            assert redis.llen(redis_queue.get_inflight_name(receipt)) == 0
        finally:
            self.delete_all_list(redis)

    @pytest.mark.serial
    def test_polling_with_empty_inbox(self, redis, redis_queue):
        self.delete_all_list(redis)
        (receipt, elements) = redis_queue.poll(10)
        assert len(elements) == 0
        assert redis.llen(Buffer.INBOX.name()) == 0
        assert redis.llen(redis_queue.get_inflight_name(receipt)) == 0

    @pytest.mark.serial
    def test_polling_with_zero_count(self, redis, redis_queue):
        with self.given_inbox_with_one_element(redis, redis_queue):
            (receipt, elements) = redis_queue.poll(0)
            assert len(elements) == 0
            assert redis.llen(Buffer.INBOX.name()) == 1
            assert redis.llen(redis_queue.get_inflight_name(receipt)) == 0

    @pytest.mark.serial
    def test_polling_with_negative_count(self, redis, redis_queue):
        with self.given_inbox_with_one_element(redis, redis_queue):
            (receipt, elements) = redis_queue.poll(-1)
            assert len(elements) == 0
            assert redis.llen(Buffer.INBOX.name()) == 1
            assert redis.llen(redis_queue.get_inflight_name(receipt)) == 0

    @pytest.mark.serial
    def test_acknowledged_messages(self, redis, redis_queue):
        with self.given_inbox_with_one_element(redis, redis_queue):
            (receipt, elements) = redis_queue.poll(10)
            redis_queue.acknowledge(receipt)
            assert len(elements) > 0
            assert redis.llen(Buffer.INBOX.name()) == 0
            assert redis.llen(redis_queue.get_inflight_name(receipt)) == 0
            assert len(redis.keys("*")) == 0

    @pytest.mark.serial
    def test_messages_serialization_after_poll(self, redis, redis_queue):
        self.delete_all_list(redis)
        notification = (
            "{'id': '0ba0ff51-ec82-4835-b828-a24fec6124ab', 'type': 'email', 'email_address': 'success@simulator.amazonses.com'}"
        )
        redis_queue.publish(notification)
        (_, elements) = redis_queue.poll(1)

        assert len(elements) > 0
        assert type(elements) is list
        assert type(elements[0]) is str
        assert elements[0] == notification

        self.delete_all_list(redis)


@pytest.mark.usefixtures("notify_api")
class TestMockQueue:
    @pytest.fixture
    def mock_queue(self):
        return MockQueue()

    def test_polling_messages_from_queue(self, mock_queue):
        (receipt, elements) = mock_queue.poll(10)
        assert elements is not None
        assert len(elements) == 10

    def test_publish_mesages_on_queue(self, mock_queue):
        element = generate_element()
        mock_queue.publish(element)

        # This should not add change internal data structure
        # or differ from a random output generation due to the
        # nature of MockQueue.
        (_, elements) = mock_queue.poll(1)
        assert elements is not None
        assert len(elements) == 1
        assert element != elements[0]

    def test_acknowledged_messages(self, mock_queue):
        mock_queue.acknowledge([1, 2, 3])
