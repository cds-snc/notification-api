import os

from dotenv import load_dotenv
from locust import HttpUser, constant_pacing, events, task
from soak_utils import url_with_prefix

load_dotenv()


@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument("--ref", type=str, default="test", help="reference")
    parser.add_argument("--type", type=str, default="email", help="email or sms")


class NotifyApiUser(HttpUser):
    wait_time = constant_pacing(1)  # each user makes one post per second

    def __init__(self, *args, **kwargs):
        self.host = url_with_prefix(self.host, "api")

        super(NotifyApiUser, self).__init__(*args, **kwargs)
        self.headers = {"Authorization": f"apikey-v1 {os.getenv('API_KEY')}"}
        self.email_template = os.getenv("EMAIL_TEMPLATE_ID")
        self.sms_template = os.getenv("SMS_TEMPLATE_ID")
        self.email_address = "success@simulator.amazonses.com"
        self.phone_number = "+16135550123" # INTERNAL_TEST_NUMBER
        self.reference_id = self.environment.parsed_options.ref
        self.type = self.environment.parsed_options.type

    @task(1)
    def send_notification(self):
        if self.type == "email":
            json = {"email_address": self.email_address, "template_id": self.email_template, "reference": self.reference_id}
            self.client.post("/v2/notifications/email", json=json, headers=self.headers)
        else:
            json = {"phone_number": self.phone_number, "template_id": self.sms_template, "reference": self.reference_id}
            self.client.post("/v2/notifications/sms", json=json, headers=self.headers)