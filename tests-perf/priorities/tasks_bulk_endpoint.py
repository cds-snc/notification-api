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
    wait_time = constant_pacing(10)  # run once every 10 second
    host = Config.API_HOST_NAME

    @task
    def send_bulk(self):
        json = {
            "name": f"{datetime.utcnow().isoformat()} {self.environment.parsed_options.ref}",
            "template_id": Config.BULK_EMAIL_TEMPLATE,
            "csv": rows_to_csv([["email address"], *job_line(Config.EMAIL_TO, Config.JOB_SIZE)]),
        }
        self.client.post("/v2/notifications/bulk", json=json, headers=api_headers(Config.API_KEY))
