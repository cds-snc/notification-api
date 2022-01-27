import json
import random
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Protocol
from uuid import UUID, uuid4

from faker import Faker
from faker.providers import BaseProvider
from flask import current_app
from flask_redis.client import FlaskRedis

from app import models

# TODO: Move data generation into another module, similar to app.aws.mocks?
fake = Faker()


class NotifyProvider(BaseProvider):
    """Faker provider for the Notify namespace."""

    NOTIFICATION_STATUS = [
        models.NOTIFICATION_CREATED,
        models.NOTIFICATION_SENDING,
        models.NOTIFICATION_SENT,
        models.NOTIFICATION_DELIVERED,
    ]

    SERVICES = [
        "Chair department",
        "Desk department",
        "Pencil department (deprecated)",
        "Gather.town virtual folks",
        "Snowstorm alerting service",
    ]

    PROCESS_TYPES = [
        "normal",
        "priority",
    ]

    TEMPLATES = [
        "Order a chair",
        "Order a pen",
        "How to dress a cat",
        "How to dress your husband",
        "COVID-19 guidelines",
    ]

    NOTIFICATION_TYPE = [models.EMAIL_TYPE, models.SMS_TYPE]

    def notification(self) -> models.Notification:
        template = self.template()
        service = template.service
        created_at = fake.date_time_this_month()
        email = "success@simulator.amazonses.com"
        data = {
            "id": str(uuid4()),
            "to": "success@simulator.amazonses.com",
            "job_id": None,
            "job": None,
            "service_id": service.id,
            "service": service,
            "template_id": template.id,
            "template_version": 1,
            "template": template,
            "status": self.status(),
            "reference": str(uuid4()),
            "created_at": created_at,
            "sent_at": None,
            "billable_units": None,
            "personalisation": None,
            "notification_type": template.template_type,
            "api_key": None,
            "api_key_id": None,
            "key_type": None,
            "sent_by": self.provider(),
            "updated_at": created_at,
            "client_reference": None,
            "job_row_number": None,
            "rate_multiplier": None,
            "international": False,
            "phone_prefix": None,
            "normalised_to": email,
            "reply_to_text": fake.email(),
            "created_by_id": None,
            "postage": None,
        }
        return models.Notification(**data)

    def notification_type(self) -> str:
        """Gets a random notification type."""
        return random.choice(self.NOTIFICATION_TYPE)

    def process_type(self) -> str:
        """Gets a random process type."""
        return random.choice(self.PROCESS_TYPES)

    def provider(self) -> str:
        """Gets a random provider."""
        return random.choice(models.PROVIDERS)

    def service(self) -> models.Service:
        data = {
            "id": str(uuid4()),
            "name": self.service_name(),
            "message_limit": 1000,
            "restricted": False,
            "email_from": fake.pybool(),
            "created_by": str(uuid4()),
            "crown": False,
        }
        return models.Service(**data)

    def service_name(self) -> str:
        """Gets a random service name"""
        return random.choice(self.SERVICES)

    def status(self) -> str:
        """Gets a random notification status."""
        return random.choice(self.NOTIFICATION_STATUS)

    def template(self) -> models.Template:
        """Gets a random template."""
        notification_type = self.notification_type()
        service = self.service()
        data = {
            "id": str(uuid4()),
            "name": self.template_name(),
            "template_type": notification_type,
            "content": fake.paragraph(5),
            "service_id": service.id,
            "service": service,
            "created_by": service.created_by,
            "reply_to": None,
            "hidden": False,
            "folder": None,
            "process_type": self.process_type(),
        }
        data["subject"] = fake.sentence(6)
        template = models.Template(**data)
        return template

    def template_name(self) -> str:
        """Gets a random template name."""
        return random.choice(self.TEMPLATES)


fake.add_provider(NotifyProvider)


def generate_notification():
    while True:
        yield fake.notification()


def generate_notifications(count=10) -> list[Dict]:
    notifications = generate_notification()
    return [next(notifications) for i in range(0, count)]


class Buffer(Enum):
    INBOX = "inbox"
    IN_FLIGHT = "in-flight"

    def name(self, suffix=None):
        return f"{self.value}:{suffix}" if suffix else self.value


class Serializable(Protocol):
    def serialize(self) -> dict:
        """Serialize current object into a dictionary"""


class Queue(ABC):
    """Queue interface for custom buffer.

    Implementations should allow to poll from the queue and acknowledge
    read messages once work is done on these.
    """

    @abstractmethod
    def poll(self, count=10) -> tuple[UUID, list[Dict]]:
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
            tuple[UUID, list[Dict]]: Gets polling receipt and list of polled notifications.
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
    def publish(self, serializable: Serializable):
        pass


# TODO: Check if we want to move the queue API and implementations into the utils project.
class RedisQueue(Queue):
    """Implementation of a queue using Redis."""

    LUA_MOVE_TO_INFLIGHT = "move-in-inflight"

    scripts: Dict[str, Any] = {}

    def __init__(self, redis_client: FlaskRedis, inbox_suffix=None) -> None:
        self._inbox = Buffer.INBOX.name(inbox_suffix)
        self._redis_client = redis_client
        self._limit = current_app.config["BATCH_INSERTION_CHUNK_SIZE"]
        self.__register_scripts()

    def poll(self, count=10) -> tuple[UUID, list[Dict]]:
        receipt = uuid4()
        in_flight_key = self.get_inflight_name(receipt)
        results = self.__move_to_inflight(in_flight_key, count)
        return (receipt, results)

    def acknowledge(self, receipt: UUID):
        inflight_name = self.get_inflight_name(receipt)
        self._redis_client.delete(inflight_name)

    def get_inflight_name(self, receipt: UUID = uuid4()) -> str:
        return f"{Buffer.IN_FLIGHT.value}:{str(receipt)}"

    def publish(self, serializable: Serializable):
        serialized: str = json.dumps(serializable.serialize())
        self._redis_client.rpush(self._inbox, serialized)

    def __move_to_inflight(self, in_flight_key: str, count: int) -> list[dict]:
        results = self.scripts[self.LUA_MOVE_TO_INFLIGHT](args=[self._inbox, in_flight_key, count])
        outcome = [result.decode("utf-8") for result in results]
        return outcome

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
    """Implementation of a queue that spits out randomly generated notifications.

    Do not use in production!"""

    def poll(self, count=10) -> tuple[UUID, list[Dict]]:
        receipt = uuid4()
        notifications = generate_notifications(count)
        return (receipt, notifications)

    def acknowledge(self, receipt: UUID):
        pass

    def publish(self, serializable: Serializable):
        pass
