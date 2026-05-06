import csv
import os
from io import StringIO
from typing import Iterator, List

# from app/config.py
# This does not do the boto call to send, but instead immediately creates a "delivered" receipt
INTERNAL_TEST_NUMBER = "+16135550123"


class _Config:
    @property
    def EMAIL_ADDRESS(self):
        return os.environ.get("PERF_TEST_EMAIL_ADDRESS", "success@simulator.amazonses.com")

    @property
    def PHONE_NUMBER(self):
        return os.environ.get("PERF_TEST_PHONE_NUMBER", INTERNAL_TEST_NUMBER)

    @property
    def EMAIL_TEMPLATE_ID_ONE_VAR(self):
        return os.environ.get("PERF_TEST_EMAIL_TEMPLATE_ID_ONE_VAR")

    @property
    def SMS_TEMPLATE_ID_ONE_VAR(self):
        return os.environ.get("PERF_TEST_SMS_TEMPLATE_ID_ONE_VAR")

    @property
    def API_KEY(self):
        return os.environ.get("PERF_TEST_API_KEY")

    @property
    def WAF_SECRET(self):
        return os.environ.get("PERF_TEST_WAF_SECRET")

    @property
    def HOST(self):
        return os.environ.get("PERF_TEST_DOMAIN", "https://api.staging.notification.cdssandbox.xyz")

    def check(self):
        for key in ["EMAIL_ADDRESS", "PHONE_NUMBER", "EMAIL_TEMPLATE_ID_ONE_VAR", "SMS_TEMPLATE_ID_ONE_VAR", "API_KEY"]:
            if not getattr(self, key):
                raise ValueError(f"{key} is not set")


Config = _Config()


def rows_to_csv(rows: List[List[str]]):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerows(rows)
    return output.getvalue()


def generate_job_rows(data: str, number_of_lines: int, prefix: str = "") -> Iterator[List[str]]:
    return map(lambda n: [data, f"{prefix} {n}"], range(0, number_of_lines))
