import os
import sys

from dotenv import load_dotenv
from locust import HttpUser, constant_pacing, events, task

load_dotenv()

# Match with app/config.py
INTERNAL_TEST_NUMBER = "+16135550123"
INTERNAL_TEST_EMAIL_ADDRESS = "internal.test@cds-snc.ca"


@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument("--type", type=str, default="none", help="email or sms")


class NotifyApiUser(HttpUser):
    wait_time = constant_pacing(1)  # each user makes one post per second

    def __init__(self, *args, **kwargs):
        super(NotifyApiUser, self).__init__(*args, **kwargs)
        self.headers = {"Authorization": f"apikey-v1 {os.getenv('API_KEY')}"}
        self.email_template = os.getenv("EMAIL_TEMPLATE_ID")
        self.sms_template = os.getenv("SMS_TEMPLATE_ID")
        self.email_address = INTERNAL_TEST_EMAIL_ADDRESS
        self.phone_number = INTERNAL_TEST_NUMBER
        self.type = self.environment.parsed_options.type

        if self.type not in ["email", "sms"]:
            print("Invalid type. Must have --type email or --type sms")
            sys.exit()

    @task(1)
    def send_notification(self):
        if self.type == "email":
            json = {"email_address": self.email_address, "template_id": self.email_template}
            self.client.post("/v2/notifications/email", json=json, headers=self.headers)
        else:
            json = {"phone_number": self.phone_number, "template_id": self.sms_template}
            self.client.post("/v2/notifications/sms", json=json, headers=self.headers)
