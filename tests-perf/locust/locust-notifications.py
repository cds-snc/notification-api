import sys, os
sys.path.append(os.path.abspath(os.path.join("..", "tests_smoke")))

from datetime import datetime
from dotenv import load_dotenv
from locust import HttpUser, constant_pacing, task
from tests_smoke.smoke.common import job_line, rows_to_csv

load_dotenv()


class NotifyApiUser(HttpUser):

    wait_time = constant_pacing(60)
    host = os.getenv("LOAD_TEST_DOMAIN", "https://api.staging.notification.cdssandbox.xyz")

    def __init__(self, *args, **kwargs):
        super(NotifyApiUser, self).__init__(*args, **kwargs)

        self.headers = {"Authorization": os.getenv("TEST_AUTH_HEADER")}
        self.email = "success@simulator.amazonses.com"
        self.template_id = "5ebee3b7-63c0-4052-a8cb-387b818df627"

    @task(1)
    def send_email_notifications(self):
        json = self.__email_json("a59b313d-8de2-4973-ac2f-66de7ec0b239")

        self.client.post("/v2/notifications/email", json=json, headers=self.headers)

    @task(2)
    def send_email_with_attachment_notifications(self):
        personalisation = {
            "application_file": {
                "file": "Q29udGVudCBvZiBBdHRhY2hlZCBmaWxl",
                "filename": "attached_file.txt",
                "sending_method": "attach",
            }
        }
        json = self.__email_json(self.template_id, personalisation)

        self.client.post("/v2/notifications/email", json=json, headers=self.headers)

    @task(4)
    def send_email_with_link_notifications(self):
        personalisation = {
            "application_file": {
                "file": "Q29udGVudCBvZiBBdHRhY2hlZCBmaWxl",
                "filename": "attached_file.txt",
                "sending_method": "link",
            }
        }
        json = self.__email_json(self.template_id, personalisation)


        self.client.post("/v2/notifications/email", json=json, headers=self.headers)

    @task(8)
    def send_bulk_notifications(self):
        json = {
            "name": f"My bulk name {datetime.utcnow().isoformat()}",
            "template_id": self.template_id,
            "csv": rows_to_csv([["email address", "application_file"], *job_line(self.email, 2)])
        }

        self.client.post("/v2/notifications/bulk", json=json, headers=self.headers)

    @task(16)
    def send_sms_notifications(self):
        json = {
            "phone_number": "12897682684",
            "template_id": "83d01f06-a818-4134-bd69-ce90a2949280"
        }

        self.client.post("/v2/notifications/sms", json=json, headers=self.headers)

    def __email_json(self, template_id, personalisation = {}):
        return {
            "email_address": self.email,
            "template_id": template_id,
            "personalisation": personalisation,
        }
