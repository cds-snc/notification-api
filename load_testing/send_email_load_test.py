import os
from locust import task

from send_notification_load_test import SendNotification


class SendEmail(SendNotification):
    @task
    def send_email(self):
        headers = {
            'Authorization': f"Bearer {self._get_jwt().decode('utf-8')}"
        }
        payload = {
            'template_id': self.email_template_id,
            'email_address': 'test-email@not-a-real-email.com'
        }
        self.client.post(
            '/v2/notifications/email',
            json=payload,
            headers=headers,
            verify=os.getenv('REQUESTS_CA_BUNDLE')
        )
