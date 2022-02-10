import os

from dotenv import load_dotenv
from locust import HttpUser, constant_pacing, task

load_dotenv()


class NotifyApiUser(HttpUser):
    wait_time = constant_pacing(1)  # each user makes one post per second

    def __init__(self, *args, **kwargs):
        super(NotifyApiUser, self).__init__(*args, **kwargs)
        self.headers = {"Authorization": os.getenv("PERF_TEST_AUTH_HEADER")}
        self.email_address = os.getenv("PERF_TEST_EMAIL", "success@simulator.amazonses.com")
        self.email_template = os.getenv("PERF_TEST_EMAIL_TEMPLATE_ID")

    @task(1)
    def send_email_notifications(self):
        json = self.__email_json(self.email_template)
        self.client.post("/v2/notifications/email", json=json, headers=self.headers)

    def __email_json(self, template_id, personalisation={}):
        return {
            "email_address": self.email_address,
            "template_id": template_id,
            "personalisation": personalisation,
        }
