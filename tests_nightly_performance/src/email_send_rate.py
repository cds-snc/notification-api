from datetime import datetime

from common import Config, generate_job_rows, rows_to_csv
from locust import HttpUser, constant_pacing, task

BULK_SIZE = 2000


class NotifyApiUser(HttpUser):

    wait_time = constant_pacing(60)  # 60 seconds between each task

    def __init__(self, *args, **kwargs):
        super(NotifyApiUser, self).__init__(*args, **kwargs)
        Config.check()
        self.headers = {"Authorization": f"ApiKey-v1 {Config.API_KEY}"}

    @task(1)
    def send_bulk_emails(self):
        json = {
            "name": f"Email send rate test {datetime.utcnow().isoformat()}",
            "template_id": Config.EMAIL_TEMPLATE_ID_ONE_VAR,
            "csv": rows_to_csv([["email address", "var"], *generate_job_rows(Config.EMAIL_ADDRESS, BULK_SIZE)])
        }
        self.client.post("/v2/notifications/bulk", json=json, headers=self.headers)
