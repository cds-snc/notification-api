import os
from locust import task

from send_notification_load_test import SendNotification


class SendSms(SendNotification):
    @task
    def send(self):
        headers = {
            'Authorization': f"Bearer {self._get_jwt().decode('utf-8')}"
        }
        payload = {
            'template_id': self.sms_template_id,
            'sms_sender_id': self.sms_sender_id,
            'phone_number': '+16502532222'
        }
        self.client.post(
            '/v2/notifications/sms',
            json=payload,
            headers=headers,
            verify=os.getenv('REQUESTS_CA_BUNDLE')
        )
