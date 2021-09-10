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
        self.json = {
            "email_address": "success@simulator.amazonses.com",
            "template_id": "5ebee3b7-63c0-4052-a8cb-387b818df627",
            "personalisation": {},
        }

    @task(1)
    def send_email_notifications(self):
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
            "var": {
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
            "csv": rows_to_csv([["email address", "var"], *job_line(self.json["email_address"], 2)])
        }

        self.client.post("/v2/notifications/bulk", json=self.json, headers=self.headers)

    @task(16)
    def send_sms_notifications(self):
        self.json = {
            "phone_number": 12897682684,
            "template_id": "d8234b4d-4def-4ad6-aafe-526a24ee5f19",
            "var": "var"
        }

        self.client.post("/v2/notifications/sms", json=self.json, headers=self.headers)
