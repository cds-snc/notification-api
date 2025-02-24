from datetime import datetime

from common import Config, generate_job_rows, rows_to_csv
from locust import HttpUser, constant_pacing, task

BULK_SIZE = 2000

# Note that task weights add up to 100
# If you add / remove tasks please keep the sum 100


class NotifyApiUser(HttpUser):

    wait_time = constant_pacing(60)  # 60 seconds between each task

    def __init__(self, *args, **kwargs):
        super(NotifyApiUser, self).__init__(*args, **kwargs)
        Config.check()
        self.headers = {"Authorization": f"ApiKey-v1 {Config.API_KEY}"}

    @task(35)
    def send_one_email(self):
        json = {
            "email_address": Config.EMAIL_ADDRESS,
            "template_id": Config.EMAIL_TEMPLATE_ID_ONE_VAR,
            "personalisation": {"var": "single email"},
        }
        self.client.post("/v2/notifications/email", json=json, headers=self.headers)

    @task(35)
    def send_one_sms(self):
        json = {
            "phone_number": Config.PHONE_NUMBER,
            "template_id": Config.SMS_TEMPLATE_ID_ONE_VAR,
            "personalisation": {"var": "single sms"},
        }
        self.client.post("/v2/notifications/sms", json=json, headers=self.headers)

    @task(5)
    def send_email_with_attachment(self):
        json = {
            "email_address": Config.EMAIL_ADDRESS,
            "template_id": Config.EMAIL_TEMPLATE_ID_ONE_VAR,
            "personalisation": {
                "var": "email with attachment",
                "attached_file": {
                    "file": "Q29udGVudCBvZiBBdHRhY2hlZCBmaWxl",
                    "filename": "attached_file.txt",
                    "sending_method": "attach",
                }
            }
        }
        self.client.post("/v2/notifications/email", json=json, headers=self.headers)

    @task(5)
    def send_email_with_link_notifications(self):
        json = {
            "email_address": Config.EMAIL_ADDRESS,
            "template_id": Config.EMAIL_TEMPLATE_ID_ONE_VAR,
            "personalisation": {
                "var": {
                    "file": "Q29udGVudCBvZiBBdHRhY2hlZCBmaWxl",
                    "filename": "attached_file.txt",
                    "sending_method": "link",
                }
            }
        }
        self.client.post("/v2/notifications/email", json=json, headers=self.headers)

    @task(20)
    def send_bulk_emails(self):
        json = {
            "name": f"Email send rate test {datetime.utcnow().isoformat()}",
            "template_id": Config.EMAIL_TEMPLATE_ID_ONE_VAR,
            "csv": rows_to_csv([["email address", "var"], *generate_job_rows(Config.EMAIL_ADDRESS, 2)])
        }
        self.client.post("/v2/notifications/bulk", json=json, headers=self.headers)
