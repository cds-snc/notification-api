import json
import random

from abc import ABC, abstractmethod
from app import models
from enum import Enum
from faker import Faker
from faker.providers import BaseProvider
from flask import current_app
from flask_redis.client import FlaskRedis
from typing import Any, Dict, Protocol
from uuid import UUID, uuid4


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

    TEMPLATE_TYPES = [models.EMAIL_TYPE, models.SMS_TYPE]

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
        template_type = self.template_type()
        service = self.service()
        data = {
            "id": str(uuid4()),
            "name": self.template_name(),
            "template_type": template_type,
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

    def template_type(self) -> str:
        """Gets a random template type."""
        return random.choice(self.TEMPLATE_TYPES)


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


class Serializable(Protocol):
    def serialize(self) -> dict:
        """Serialize current object into a dictionary"""


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
    def publish(self, serializable: Serializable):
        pass


# TODO: Check if we want to move the queue API and implementations into the utils project.
class RedisQueue(Queue):
    """Implementation of a queue using Redis."""

    def __init__(self, redis_client: FlaskRedis) -> None:
        self.redis_client = redis_client
        self.limit = current_app.config["BATCH_INSERTION_CHUNK_SIZE"]

    def poll(self, count=10) -> list[Dict]:
        in_flight_key = self.__get_inflight_name()
        pipeline = self.redis_client.pipeline()
        serialized = pipeline.lrange(Buffer.INBOX.value, 0, self.limit)
        pipeline.rpush(in_flight_key, serialized)
        pipeline.ltrim(Buffer.INBOX.value, self.limit, -1)
        pipeline.execute()
        messages = list(map(json.loads, serialized))
        return messages

    def acknowledge(self, receipt: UUID):
        inflight_name = self.__get_inflight_name(receipt)
        self.redis_client.delete(inflight_name)

    def publish(self, serializable: Serializable):
        serialized: str = json.dumps(serializable.serialize())
        self.redis_client.rpush(Buffer.INBOX.value, serialized)

    def __in_flight(self) -> list[Any]:
        return self.redis_client.lrange(Buffer.INBOX.value, 0, self.limit)

    def __get_inflight_name(self, receipt: UUID = uuid4()) -> str:
        return f"{Buffer.IN_FLIGHT.value}:{str(receipt)}"


class MockQueue(Queue):
    """Implementation of a queue that spits out randomly generated notifications.

    Do not use in production!"""

    def poll(self, count=10) -> list[Dict]:
        return generate_notifications(count)

    def acknowledge(self, receipt: UUID):
        pass

    def publish(self, serializable: Serializable):
        pass
