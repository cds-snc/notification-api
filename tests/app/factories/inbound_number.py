from random import choice
import string

from app.models import InboundNumber, Service


def sample_inbound_number(service: Service = None, number: str = None) -> InboundNumber:
    return InboundNumber(
        number=number or _random_phone_number(),
        provider='some provider',
        active=True,
        service=service
    )


# Should match phonumbers library validations for US
def _random_phone_number() -> str:
    return f"+1267{choice('23456789')}{''.join(choice(string.digits) for _ in range(6))}"  # nosec
