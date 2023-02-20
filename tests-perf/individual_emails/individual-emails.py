import os
import uuid

from dotenv import load_dotenv
from locust import HttpUser, constant_pacing, events, task

load_dotenv()


@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument("--ref", type=str, default="test", help="Prefix for reference")


class NotifyApiUser(HttpUser):
    wait_time = constant_pacing(1)  # each user makes one post per second

    def __init__(self, *args, **kwargs):
        super(NotifyApiUser, self).__init__(*args, **kwargs)
        self.headers = {"Authorization": os.getenv("PERF_TEST_AUTH_HEADER")}
        self.email_address = os.getenv("PERF_TEST_EMAIL", "success@simulator.amazonses.com")
        self.email_template = os.getenv("PERF_TEST_EMAIL_TEMPLATE_ID")

    @task(1)
    def send_email(self):
        reference_id = self.environment.parsed_options.ref
        json = {"email_address": self.email_address, "template_id": self.email_template, "reference": reference_id}
        self.client.post("/v2/notifications/email", json=json, headers=self.headers)

    @task(0)
    def send_email_with_file_attachment(self):
        reference_id = self.environment.parsed_options.ref
        json = {
            "email_address": "stephen.astels@cds-snc.ca",  # self.email_address,
            "template_id": self.email_template,
            "reference": reference_id,
            "personalisation": {
                "attached_file": {
                    "file": "SGVsbG8gdGhlcmUgaG93IGFyZSB5b3U=",
                    "filename": "test_file.txt",
                    "sending_method": "attach",
                }
            },
        }
        self.client.post("/v2/notifications/email", json=json, headers=self.headers)

    @task(0)
    def send_email_with_5_file_attachments(self):
        reference_id = self.environment.parsed_options.ref
        personalisation = {}
        for _ in range(5):
            personalisation[f"attached_file{i}"] = {
                "file": "SGVsbG8gdGhlcmUgaG93IGFyZSB5b3U=",
                "filename": "test_file.txt",
                "sending_method": "attach",
            }
        json = {
            "email_address": self.email_address,
            "template_id": self.email_template,
            "reference": reference_id,
            "personalisation": personalisation,
        }
        self.client.post("/v2/notifications/email", json=json, headers=self.headers)
