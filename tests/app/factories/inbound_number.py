import random
import string

from app.models import InboundNumber, Service


def sample_inbound_number(service: Service = None, number: str = None) -> InboundNumber:
    return InboundNumber(
        number=number or _random_phone_number(),
        provider='some provider',
        active=True,
        service=service
    )


def _random_phone_number() -> str:
    return f"+1{''.join(random.choice(string.digits) for _ in range(10))}"  # nosec
