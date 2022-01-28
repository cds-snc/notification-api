import random
import string
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict
from uuid import UUID, uuid4

from flask import current_app
from flask_redis.client import FlaskRedis


def generate_element(length=10) -> str:
    elem = "".join(random.choice(string.ascii_lowercase) for i in range(length))
    return elem


def generate_elements(count=10) -> list[str]:
    return [generate_element(count) for s in range(count)]


class Buffer(Enum):
    INBOX = "inbox"
    IN_FLIGHT = "in-flight"

    def name(self, suffix=None):
        return f"{self.value}:{suffix}" if suffix else self.value


class Queue(ABC):
    """Queue interface for custom buffer.

    Implementations should allow to poll from the queue and acknowledge
    read messages once work is done on these.
    """

    @abstractmethod
    def poll(self, count=10) -> tuple[UUID, list[str]]:
        """Gets messages out of the queue.

        Each polling is associated with a UUID acting as a receipt. This
        can later be used in conjunction with the `acknowledge` function
        to confirm that the polled messages were properly processed.
        This will delete the in-flight messages and these will not get
        back into the main inbox. Failure to achknowledge the polled
        messages will get these back into the inbox after a preconfigured
        timeout has passed, ready to be retried.

        Args:
            count (int, optional): Number of messages to get out of the queue. Defaults to 10.

        Returns:
            tuple[UUID, list[str]]: Gets polling receipt and list of polled notifications.
        """
        pass

    @abstractmethod
    def acknowledge(self, receipt: UUID):
        """Acknowledges reception and processing of provided messages IDs.

        Once the acknowledgement is done, the messages will get their in-flight
        status removed and will not get served again through the `poll` method.

        Args:
            message_ids (list[int]): [description]
        """
        pass

    @abstractmethod
    def publish(self, message: str):
        """Publishes the message into the buffer queue.

        The message is put onto the back of the queue to be later processed
        in a FIFO order.

        Args:
            message (str): Message to store into the queue.
        """
        pass


# TODO: Check if we want to move the queue API and implementations into the utils project.
class RedisQueue(Queue):
    """Implementation of a queue using Redis."""

    LUA_MOVE_TO_INFLIGHT = "move-in-inflight"

    scripts: Dict[str, Any] = {}

    def __init__(self, redis_client: FlaskRedis, inbox_suffix=None) -> None:
        self._inbox = Buffer.INBOX.name(inbox_suffix)
        self._redis_client = redis_client
        self.__register_scripts()

    def poll(self, count=10) -> tuple[UUID, list[str]]:
        receipt = uuid4()
        in_flight_key = self.get_inflight_name(receipt)
        results = self.__move_to_inflight(in_flight_key, count)
        return (receipt, results)

    def acknowledge(self, receipt: UUID):
        inflight_name = self.get_inflight_name(receipt)
        self._redis_client.delete(inflight_name)

    def get_inflight_name(self, receipt: UUID = uuid4()) -> str:
        return f"{Buffer.IN_FLIGHT.value}:{str(receipt)}"

    def publish(self, message: str):
        self._redis_client.rpush(self._inbox, message)

    def __move_to_inflight(self, in_flight_key: str, count: int) -> list[str]:
        results = self.scripts[self.LUA_MOVE_TO_INFLIGHT](args=[self._inbox, in_flight_key, count])
        decoded = [result.decode("utf-8") for result in results]
        return decoded

    def __register_scripts(self):
        self.scripts[self.LUA_MOVE_TO_INFLIGHT] = self._redis_client.register_script(
            """
            local DEFAULT_CHUNK = 99

            local source        = ARGV[1]
            local destination   = ARGV[2]
            local source_size   = tonumber(redis.call("LLEN", source))
            local count         = math.min(source_size, tonumber(ARGV[3]))

            local chunk_size    = math.min(math.max(0, count-1), DEFAULT_CHUNK)
            local current       = 0
            local all           = {}

            while current < count do
                local elements = redis.call("LRANGE", source, 0, chunk_size)
                redis.call("LPUSH", destination, unpack(elements))
                redis.call("LTRIM", source, chunk_size+1, -1)
                for i=1,#elements do all[#all+1] = elements[i] end

                current    = current + chunk_size+1
                chunk_size = math.min((count-1) - current, DEFAULT_CHUNK)
            end

            return all
            """
        )


class MockQueue(Queue):
    """Implementation of a queue that spits out randomly generated elements.

    Do not use in production!"""

    def poll(self, count=10) -> tuple[UUID, list[str]]:
        receipt = uuid4()
        return (receipt, generate_elements(count))

    def acknowledge(self, receipt: UUID):
        pass

    def publish(self, message: str):
        pass
