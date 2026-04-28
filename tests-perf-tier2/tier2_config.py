import os

from dotenv import load_dotenv

load_dotenv()

# Simulated addresses — recognised by notification-api, skip real delivery.
SIMULATED_EMAIL_ADDRESSES = [
    "simulate-delivered@notification.canada.ca",
    "simulate-delivered-2@notification.canada.ca",
    "simulate-delivered-3@notification.canada.ca",
]
SIMULATED_SMS_NUMBER = "+16132532222"


class Config:
    API_HOST_NAME = os.environ.get("PERF_TEST_HOST", "https://api.staging.notification.cdssandbox.xyz")

    # Single API key for Layer 1 & 2 tests.
    API_KEY = os.environ.get("PERF_TEST_API_KEY")

    # Comma-separated list of API keys for Layer 3 multi-service tests.
    # Each key belongs to a different service.
    API_KEYS_CSV = os.environ.get("PERF_TEST_API_KEYS", "")

    SMS_TEMPLATE_ID = os.environ.get("PERF_TEST_SMS_TEMPLATE_ID")
    EMAIL_TEMPLATE_ID = os.environ.get("PERF_TEST_EMAIL_TEMPLATE_ID")

    SMS_TO = SIMULATED_SMS_NUMBER
    EMAIL_TO = SIMULATED_EMAIL_ADDRESSES[0]

    # Tier 2 limits — used by tests to know when to expect 429s.
    SMS_DAILY_LIMIT = int(os.environ.get("PERF_TEST_SMS_DAILY_LIMIT", "1500"))
    EMAIL_DAILY_LIMIT = int(os.environ.get("PERF_TEST_EMAIL_DAILY_LIMIT", "10000"))

    @classmethod
    def validate_single(cls):
        """Validate config for single-service tests (Layer 1 & 2)."""
        for key in ["API_KEY", "SMS_TEMPLATE_ID"]:
            if not getattr(cls, key):
                raise ValueError(f"PERF_TEST_{key} is not set")

    @classmethod
    def validate_multi(cls):
        """Validate config for multi-service tests (Layer 3)."""
        cls.validate_single()
        if not cls.API_KEYS_CSV:
            raise ValueError("PERF_TEST_API_KEYS is not set (comma-separated list of API keys)")

    @classmethod
    def api_key_pool(cls):
        """Return a list of API keys for multi-service tests."""
        if not cls.API_KEYS_CSV:
            return [cls.API_KEY]
        return [k.strip() for k in cls.API_KEYS_CSV.split(",") if k.strip()]
