import os

from dotenv import load_dotenv
from locust import HttpUser, constant_pacing, task, tag

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
            "template_id": "9c17633c-126a-4ad3-ad2f-b14c3a85314a",
            "personalisation": {"colour": "Fulvous"},
        }

    @task
    def task(self):
        pass

class OneOffEmailMessage(NotifyApiUser):
    @tag("one-off-email")
    @task
    def send_one_off_email_notifications(self):
        self.client.post("/v2/notifications/email", json=self.json, headers=self.headers)

class OneOffEmailWithFileAttachmentMessage(NotifyApiUser):
    @tag("one-off-email-attached")
    @task
    def send_one_off_email_with_attachment_notifications(self):
        self.json["personalisation"] = {
            "application_file": {
                "file": "Q29udGVudCBvZiBBdHRhY2hlZCBmaWxl",
                "filename": "attached_file.txt",
                "sending_method": "attach",
            }
        }

        self.client.post("/v2/notifications/email", json=self.json, headers=self.headers)

class OneOffEmailWithLinkMessage(NotifyApiUser):
    @tag("one-off-email-link")
    @task
    def send_one_off_email_with_link_notifications(self):
        self.json["personalisation"] = {
            "var": {
                "file": "Q29udGVudCBvZiBBdHRhY2hlZCBmaWxl",
                "filename": "attached_file.txt",
                "sending_method": "link",
            }
        }

        self.client.post("/v2/notifications/email", json=self.json, headers=self.headers)
