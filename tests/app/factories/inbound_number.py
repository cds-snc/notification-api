import string
from random import choice


# Should match phonenumbers library validations for US
def _random_phone_number() -> str:
    return f"+1267{choice('23456789')}{''.join(choice(string.digits) for _ in range(6))}"  # nosec
