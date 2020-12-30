import time
import os
import jwt
from locust import HttpUser, task


class SendEmail(HttpUser):

    @task
    def send_email(self):
        headers = {
            'Authorization': f"Bearer {self._get_jwt().decode('utf-8')}"
        }
        template_id = os.getenv('LOAD_TESTING_TEMPLATE_ID')
        payload = {
            'template_id': template_id,
            'email_address': 'foo@bar.com'
        }
        self.client.post('/v2/notifications/email', json=payload, headers=headers)

    def _get_jwt(self):
        service_id = os.getenv('LOAD_TESTING_SERVICE_ID')
        jwtSecret = os.getenv('LOAD_TESTING_API_KEY')
        header = {'typ': 'JWT', 'alg': 'HS256'}
        combo = {}
        currentTimestamp = int(time.time())
        data = {
            'iss': service_id,
            'iat': currentTimestamp,
            'exp': currentTimestamp + 30,
            'jti': 'jwt_nonce'
        }
        combo.update(data)
        combo.update(header)
        encoded_jwt = jwt.encode(combo, jwtSecret, algorithm='HS256')
        return encoded_jwt
