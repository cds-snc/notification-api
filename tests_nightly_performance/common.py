import csv
import os
from io import StringIO
from typing import Iterator, List

from dotenv import load_dotenv

# from app/config.py
# This does not do the boto call to send, but instead immediately creates a "delivered" receipt
INTERNAL_TEST_NUMBER = "+16135550123"

load_dotenv()


class Config:
    EMAIL_ADDRESS = os.environ.get("PERF_TEST_EMAIL_ADDRESS", "success@simulator.amazonses.com")
    PHONE_NUMBER = os.environ.get("PERF_TEST_PHONE_NUMBER", INTERNAL_TEST_NUMBER)
    EMAIL_TEMPLATE_ID_ONE_VAR = os.environ.get("PERF_TEST_EMAIL_TEMPLATE_ID_ONE_VAR")
    SMS_TEMPLATE_ID_ONE_VAR = os.environ.get("PERF_TEST_SMS_TEMPLATE_ID_ONE_VAR")
    API_KEY = os.environ.get("PERF_TEST_API_KEY")

    @staticmethod
    def check():
        for key in ["EMAIL_ADDRESS", "PHONE_NUMBER", "EMAIL_TEMPLATE_ID_ONE_VAR", "SMS_TEMPLATE_ID_ONE_VAR", "API_KEY"]:
            if not getattr(Config, key):
                raise ValueError(f"{key} is not set")


def rows_to_csv(rows: List[List[str]]):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerows(rows)
    return output.getvalue()


def generate_job_rows(data: str, number_of_lines: int, prefix: str = "") -> Iterator[List[str]]:
    return map(lambda n: [data, f"{prefix} {n}"], range(0, number_of_lines))
