import random
from app.mobile_app import MobileAppType


def sample_mobile_app_type():
    return random.choice(MobileAppType.values())  # nosec
