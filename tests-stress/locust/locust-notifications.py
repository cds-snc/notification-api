import os

from dotenv import load_dotenv
from locust import HttpUser, constant_pacing, task

load_dotenv()
API_KEY = os.getenv("TEST_API_KEY")


class NotifyApiUser(HttpUser):

    wait_time = constant_pacing(60)
    host = "https://api.staging.notification.cdssandbox.xyz"

    @task
    def send_notifications(self):
        headers = {"Authorization": API_KEY, "Content-Type": "application/json"}
        json = {
            "email_address": "success@simulator.amazonses.com",
            "template_id": "9c17633c-126a-4ad3-ad2f-b14c3a85314a",
            "personalisation": {"colour": "Fulvous"},
        }

        self.client.post("/v2/notifications/email", json=json, headers=headers)
