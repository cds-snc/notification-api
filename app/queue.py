import random
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict
from uuid import UUID, uuid4

from faker import Faker
from faker.providers import BaseProvider
from flask import current_app
from notifications_utils.clients.redis.redis_client import RedisClient

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

    def notification(self) -> models.Notification:
        created_at = fake.date_time_this_month()
        email = "success@simulator.amazonses.com"
        data = {
            "id": uuid4(),
            "to": "success@simulator.amazonses.com",
            "job_id": None,
            "job": None,
            "service_id": uuid4(),
            "service": self.service(),
            "template_id": uuid4(),
            "template_version": 1,
            "status": self.status(),
            "reference": uuid4(),
            "created_at": created_at,
            "sent_at": None,
            "billable_units": None,
            "personalisation": None,
            "notification_type": self.notification_type(),
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
        return random.choice(models.NOTIFICATION_TYPE)

    def provider(self) -> str:
        """Gets a random provider."""
        return random.choice(models.PROVIDERS)

    def service(self) -> str:
        """Gets a random service name"""
        return random.choice(self.SERVICES)

    def status(self) -> str:
        """Gets a random notification status."""
        return random.choice(self.NOTIFICATION_STATUS)


fake.add_provider(NotifyProvider)


def generate_notification():
    while True:
        yield fake.notification()


def generate_notifications(count=10):
    notifications = generate_notification()
    return [next(notifications) for i in range(0, count)]


class Buffer(Enum):
    INBOX = "INBOX"
    IN_FLIGHT = "IN-FLIGHT"


class Queue(ABC):
    """Queue interface for custom buffer.

    Implementations should allow to poll from the queue and acknowledge
    read messages once work is done on these.
    """

    @abstractmethod
    def poll(self, count=10) -> list[Dict]:
        """Gets messages out of the queue.

        Args:
            count (int, optional): Number of messages to get out of the queue. Defaults to 10.
        Returns:
            list[Any]: List of messages in the queue, from 1 up to {count} number.
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
    def publish(self, dict: Dict) -> None:
        pass


# TODO: Check if we want to move the queue API and implementations into the utils project.
class RedisQueue(Queue):
    """Implementation of a queue using Redis."""

    def __init__(self, connection: RedisClient) -> None:
        self.connection = connection
        self.limit = current_app.config["BATCH_INSERTION_CHUNK_SIZE"]

    def poll(self, count=10) -> list[Dict]:
        in_flight_key = self.__get_inflight_name()
        notifications = None

        pipeline = self.connection.pipeline()
        notifications = pipeline.lrange(Buffer.INBOX, 0, self.limit)
        pipeline.rpush(in_flight_key, notifications)
        pipeline.ltrim(Buffer.INBOX, self.limit, -1)
        pipeline.execute()

        return notifications

    def acknowledge(self, receipt: UUID):
        inflight_name = self.__get_inflight_name(receipt)
        self.connection.delete(inflight_name)

    def publish(self, dict: Dict) -> None:
        self.connection.rpush(Buffer.INBOX, dict)

    def __in_flight(self) -> list[Any]:
        return self.connection.lrange(Buffer.INBOX, 0, self.limit)

    def __get_inflight_name(self, receipt: UUID = uuid4()) -> str:
        return f"{Buffer.IN_FLIGHT}:{receipt}"


class MockQueue(Queue):
    """Implementation of a queue that spits out randomly generated notifications.

    Do not use in production!"""

    def poll(self, count=10) -> list[Dict]:
        return generate_notifications(count)

    def acknowledge(self, receipt: UUID):
        pass

    def publish(self, dict: Dict) -> None:
        pass
