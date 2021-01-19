import time
import os
import jwt
import boto3
from locust import HttpUser, task
from urllib.parse import urlparse


class SendEmail(HttpUser):

    def on_start(self):
        self.short_env = urlparse(self.environment.host).hostname.split('.')[0]  # looking for "dev" or "staging"
        self.template_id = self.read_configuration('template_id')
        self.service_id = self.read_configuration('service_id')
        self.api_key = self.read_configuration('api_key')

    def read_configuration(self, key: str) -> str:
        if f"LOAD_TESTING_{self.short_env}_{key}" in os.environ:
            return os.getenv(f"LOAD_TESTING_{self.short_env}_{key}")
        else:
            return self.read_from_ssm(key)

    def read_from_ssm(self, key: str) -> str:
        if not hasattr(self, 'boto_client'):
            self.boto_client = boto3.client('ssm')

        resp = self.boto_client.get_parameter(
            Name=f"/utility/locust/{self.short_env}/{key}",
            WithDecryption=True
        )
        return resp["Parameter"]["Value"]

    @task
    def send_email(self):
        headers = {
            'Authorization': f"Bearer {self._get_jwt().decode('utf-8')}"
        }
        payload = {
            'template_id': self.template_id,
            'email_address': 'test-email@not-a-real-email.com'
        }
        self.client.post(
            '/v2/notifications/email',
            json=payload,
            headers=headers,
            verify='/etc/pki/tls/certs/ca-bundle.trust.crt'
        )

    def _get_jwt(self) -> bytes:
        header = {'typ': 'JWT', 'alg': 'HS256'}
        combo = {}
        currentTimestamp = int(time.time())
        data = {
            'iss': self.service_id,
            'iat': currentTimestamp,
            'exp': currentTimestamp + 30,
            'jti': 'jwt_nonce'
        }
        combo.update(data)
        combo.update(header)
        encoded_jwt = jwt.encode(combo, self.api_key, algorithm='HS256')
        return encoded_jwt
