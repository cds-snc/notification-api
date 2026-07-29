from datetime import datetime

import locust_setup  # noqa: F401 - this file configures locust
from locust import HttpUser, constant_pacing, task

from config import Config
from utils import api_headers, job_line, rows_to_csv

"""
Usage:
Run the following command to execute the load test for the bulk endpoint:

locust -f ./locust_bulk_endpoint.py --headless --stop-timeout=30 --run-time=15s --host=https://api-k8s.staging.notification.cdssandbox.xyz --users=1 --html=locust.html

This will send bulk requests for all priorities of both email and SMS, with a total of 6 requests per run (1 for each priority and type).
"""


class ApiUser(HttpUser):
    wait_time = constant_pacing(60)  # run all tasks once every 60 seconds
    host = Config.API_HOST_NAME

    BULK_SEND_CONFIG = [
        {
            "template": Config.BULK_EMAIL_TEMPLATE,
            "row_name": "email address",
            "recipient": Config.EMAIL_TO,
            "job_size": Config.JOB_SIZE,
        },
        {
            "template": Config.NORMAL_EMAIL_TEMPLATE,
            "row_name": "email address",
            "recipient": Config.EMAIL_TO,
            "job_size": Config.JOB_SIZE,
        },
        {"template": Config.PRIORITY_EMAIL_TEMPLATE, "row_name": "email address", "recipient": Config.EMAIL_TO, "job_size": 10},
        {
            "template": Config.BULK_SMS_TEMPLATE,
            "row_name": "phone number",
            "recipient": Config.SMS_TO,
            "job_size": Config.JOB_SIZE,
        },
        {
            "template": Config.NORMAL_SMS_TEMPLATE,
            "row_name": "phone number",
            "recipient": Config.SMS_TO,
            "job_size": Config.JOB_SIZE,
        },
        {"template": Config.PRIORITY_SMS_TEMPLATE, "row_name": "phone number", "recipient": Config.SMS_TO, "job_size": 10},
    ]

    URL = "/v2/notifications/bulk"

    @task
    def send_bulk_email_sms_all_priorities(self):
        ref = self.environment.parsed_options.ref

        for config in self.BULK_SEND_CONFIG:
            self.client.post(
                self.URL,
                json={
                    "name": f"{datetime.utcnow().isoformat()} {ref}",
                    "template_id": config["template"],
                    "csv": rows_to_csv(
                        [
                            [config["row_name"]],
                            *job_line(
                                config["recipient"],
                                config["job_size"],
                            ),
                        ]
                    ),
                },
                headers=api_headers(Config.API_KEY, Config.WAF_SECRET),
            )
