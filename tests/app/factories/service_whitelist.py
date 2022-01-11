import string
from random import choice
from app.models import ServiceWhitelist, EMAIL_TYPE, MOBILE_TYPE, WHITELIST_RECIPIENT_TYPE
from tests.app.factories.inbound_number import _random_phone_number


def _random_email():
    user = ''.join(choice(string.ascii_letters) for _ in range(10))  # nosec
    extension = choice(['com', 'org', 'edu', 'gov'])  # nosec
    domain = ''.join(choice(string.ascii_letters) for _ in range(5))  # nosec
    return f'{user}@{domain}.{extension}'


def email_service_whitelist(service_id, email_address=None):
    if email_address:
        return ServiceWhitelist.from_string(service_id, EMAIL_TYPE, email_address)
    return ServiceWhitelist.from_string(service_id, EMAIL_TYPE, _random_email())


def sms_service_whitelist(service_id, phone_number=None):
    if phone_number:
        return ServiceWhitelist.from_string(service_id, MOBILE_TYPE, phone_number)
    return ServiceWhitelist.from_string(service_id, MOBILE_TYPE, _random_phone_number())


def a_service_whitelist(service_id):
    generators = {
        MOBILE_TYPE: sms_service_whitelist,
        EMAIL_TYPE: email_service_whitelist
    }

    type = choice(WHITELIST_RECIPIENT_TYPE)  # nosec
    return generators[type](service_id)
