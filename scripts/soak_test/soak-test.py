import os

from dotenv import load_dotenv
from locust import HttpUser, constant_pacing, events, task

load_dotenv()


@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument("--ref", type=str, default="test", help="reference")


class NotifyApiUser(HttpUser):
    wait_time = constant_pacing(1)  # each user makes one post per second

    def __init__(self, *args, **kwargs):
        super(NotifyApiUser, self).__init__(*args, **kwargs)
        self.headers = {"Authorization": f"apikey-v1 {os.getenv('API_KEY')}"}
        self.email_address = "success@simulator.amazonses.com"
        self.email_template = os.getenv("EMAIL_TEMPLATE_ID")

    @task(1)
    def send_email(self):
        reference_id = self.environment.parsed_options.ref
        json = {"email_address": self.email_address, "template_id": self.email_template, "reference": reference_id}
        self.client.post("/v2/notifications/email", json=json, headers=self.headers)
