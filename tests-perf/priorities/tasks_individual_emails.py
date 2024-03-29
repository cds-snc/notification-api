import random
import time

import locust_setup  # noqa: F401 - this file configures locust
from locust import HttpUser, constant_throughput, task

from config import Config
from utils import api_headers, json_data

# for 4000 requests per minute, set number of users to be 4000 / 60 = 67


class ApiUser(HttpUser):
    wait_time = constant_throughput(1)  # run once every second
    host = Config.API_HOST_NAME

    @task(75)
    def send_bulk_email(self):
        time.sleep(random.random())  # prevent users from POSTing at the same time
        self.client.post(
            "/v2/notifications/email",
            json=json_data(Config.EMAIL_TO, Config.BULK_EMAIL_TEMPLATE, self.environment.parsed_options.ref),
            headers=api_headers(Config.API_KEY),
        )

    @task(20)
    def send_normal_email(self):
        time.sleep(random.random())  # prevent users from POSTing at the same time
        self.client.post(
            "/v2/notifications/email",
            json=json_data(Config.EMAIL_TO, Config.NORMAL_EMAIL_TEMPLATE, self.environment.parsed_options.ref),
            headers=api_headers(Config.API_KEY),
        )

    @task(5)
    def send_priority_email(self):
        time.sleep(random.random())  # prevent users from POSTing at the same time
        self.client.post(
            "/v2/notifications/email",
            json=json_data(Config.EMAIL_TO, Config.PRIORITY_EMAIL_TEMPLATE, self.environment.parsed_options.ref),
            headers=api_headers(Config.API_KEY),
        )
