from datetime import datetime

import locust_setup  # noqa: F401 - this file configures locust
from locust import HttpUser, constant_pacing, task

from config import Config
from utils import api_headers, job_line, rows_to_csv

"""
Usage:
runs the bulk upload twice

locust -f ./locust_bulk_endpoint.py --headless --stop-timeout=30 --run-time=15s --host=https://api-k8s.staging.notification.cdssandbox.xyz --users=1 --html=locust.html
"""


class ApiUser(HttpUser):
    wait_time = constant_pacing(60)  # run all tasks once every 60 seconds
    host = Config.API_HOST_NAME

    @task
    def send_all_bulk_and_all_types_and_all_priorities(self):
        ref = self.environment.parsed_options.ref

        self.client.post(
            "/v2/notifications/bulk",
            json={
                "name": f"{datetime.utcnow().isoformat()} {ref}",
                "template_id": Config.BULK_EMAIL_TEMPLATE,
                "csv": rows_to_csv([["email address"], *job_line(Config.EMAIL_TO, Config.JOB_SIZE)]),
            },
            headers=api_headers(Config.API_KEY, Config.WAF_SECRET),
        )

        self.client.post(
            "/v2/notifications/bulk",
            json={
                "name": f"{datetime.utcnow().isoformat()} {ref}",
                "template_id": Config.NORMAL_EMAIL_TEMPLATE,
                "csv": rows_to_csv([["email address"], *job_line(Config.EMAIL_TO, Config.JOB_SIZE)]),
            },
            headers=api_headers(Config.API_KEY, Config.WAF_SECRET),
        )

        self.client.post(
            "/v2/notifications/bulk",
            json={
                "name": f"{datetime.utcnow().isoformat()} {ref}",
                "template_id": Config.PRIORITY_EMAIL_TEMPLATE,
                "csv": rows_to_csv([["email address"], *job_line(Config.EMAIL_TO, Config.JOB_SIZE)]),
            },
            headers=api_headers(Config.API_KEY, Config.WAF_SECRET),
        )

        self.client.post(
            "/v2/notifications/bulk",
            json={
                "name": f"{datetime.utcnow().isoformat()} {ref}",
                "template_id": Config.BULK_SMS_TEMPLATE,
                "csv": rows_to_csv([["phone number"], *job_line(Config.SMS_TO, Config.JOB_SIZE)]),
            },
            headers=api_headers(Config.API_KEY, Config.WAF_SECRET),
        )

        self.client.post(
            "/v2/notifications/bulk",
            json={
                "name": f"{datetime.utcnow().isoformat()} {ref}",
                "template_id": Config.NORMAL_SMS_TEMPLATE,
                "csv": rows_to_csv([["phone number"], *job_line(Config.SMS_TO, Config.JOB_SIZE)]),
            },
            headers=api_headers(Config.API_KEY, Config.WAF_SECRET),
        )

        self.client.post(
            "/v2/notifications/bulk",
            # Hardcode the number of lines to 10 for the priority SMS template. The goal is to test the
            # priority lane isn't affected despite its small size. The other templates are tested with the full job size.
            json={
                "name": f"{datetime.utcnow().isoformat()} {ref}",
                "template_id": Config.PRIORITY_SMS_TEMPLATE,
                "csv": rows_to_csv([["phone number"], *job_line(Config.SMS_TO, 10)]),
            },
            headers=api_headers(Config.API_KEY, Config.WAF_SECRET),
        )
