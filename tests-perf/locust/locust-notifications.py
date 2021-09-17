import sys, os
sys.path.append(os.path.abspath(os.path.join("..", "tests_smoke")))

from datetime import datetime
from dotenv import load_dotenv
from locust import HttpUser, constant_pacing, task
from tests_smoke.smoke.common import job_line, rows_to_csv

load_dotenv()
AUTH_HEADER = os.getenv("TEST_AUTH_HEADER")


class NotifyApiUser(HttpUser):

    wait_time = constant_pacing(60)
    host = "https://api.staging.notification.cdssandbox.xyz"

    def __init__(self, *args, **kwargs):
        super(NotifyApiUser, self).__init__(*args, **kwargs)

        self.headers = {"Authorization": AUTH_HEADER}
        self.template_id = "5ebee3b7-63c0-4052-a8cb-387b818df627"
        self.email = "success@simulator.amazonses.com"
        self.json = {
            "email_address": self.email,
            "template_id": self.template_id,
            "personalisation": {},
        }

    @task(1)
    def send_email_notifications(self):
        self.json = {
            "email_address": self.email,
            "template_id": "a59b313d-8de2-4973-ac2f-66de7ec0b239",
            "personalisation": {},
        }

        self.client.post("/v2/notifications/email", json=self.json, headers=self.headers)

    @task(2)
    def send_email_with_attachment_notifications(self):
        self.json["personalisation"] = {
            "application_file": {
                "file": "Q29udGVudCBvZiBBdHRhY2hlZCBmaWxl",
                "filename": "attached_file.txt",
                "sending_method": "attach",
            }
        }

        self.client.post("/v2/notifications/email", json=self.json, headers=self.headers)

    @task(4)
    def send_email_with_link_notifications(self):
        self.json["personalisation"] = {
            "application_file": {
                "file": "Q29udGVudCBvZiBBdHRhY2hlZCBmaWxl",
                "filename": "attached_file.txt",
                "sending_method": "link",
            }
        }

        self.client.post("/v2/notifications/email", json=self.json, headers=self.headers)

    @task(8)
    def send_bulk_notifications(self):
        self.json = {
            "name": f"My bulk name {datetime.utcnow().isoformat()}",
            "template_id": "5ebee3b7-63c0-4052-a8cb-387b818df627",
            "csv": rows_to_csv([["email address", "application_file"], *job_line(self.email, 2)])
        }

        self.client.post("/v2/notifications/bulk", json=self.json, headers=self.headers)

    @task(16)
    def send_sms_notifications(self):
        self.json = {
            "phone_number": "12897682684",
            "template_id": "83d01f06-a818-4134-bd69-ce90a2949280"
        }

        self.client.post("/v2/notifications/sms", json=self.json, headers=self.headers)
