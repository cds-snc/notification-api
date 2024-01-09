import time
import os
import jwt
import boto3
from locust import HttpUser, task, events
import gevent
from urllib.parse import urlparse


@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument(
        '--email-limit', type=int, env_var='LOCUST_EMAIL_LIMIT', default=10, help='Number of emails to send'
    )
    parser.add_argument(
        '--email-status-query-interval',
        type=int,
        env_var='LOCUST_EMAIL_STATUS_QUERY_INTERVAL',
        default=1,
        help='Number of seconds to wait between requests to query notification status',
    )


class SendEmail(HttpUser):
    email_triggered_counter = 0
    email_completed_counter = 0
    email_limit = None
    email_status_query_interval = None

    def on_start(self):
        self.short_env = urlparse(self.environment.host).hostname.split('.')[0]  # looking for "dev" or "staging"
        self.email_template_id = self.read_configuration('email_template_id')
        self.service_id = self.read_configuration('service_id')
        self.api_key = self.read_configuration('api_key')

        self.email_limit = self.environment.parsed_options.email_limit
        self.email_status_query_interval = self.environment.parsed_options.email_status_query_interval

    def read_configuration(
        self,
        key: str,
    ) -> str:
        if f'LOAD_TESTING_{self.short_env}_{key}' in os.environ:
            return os.getenv(f'LOAD_TESTING_{self.short_env}_{key}')
        else:
            return self.read_from_ssm(key)

    def read_from_ssm(
        self,
        key: str,
    ) -> str:
        if not hasattr(self, 'boto_client'):
            self.boto_client = boto3.client('ssm')

        resp = self.boto_client.get_parameter(Name=f'/utility/locust/{self.short_env}/{key}', WithDecryption=True)
        return resp['Parameter']['Value']

    def _get_jwt(self) -> bytes:
        header = {'typ': 'JWT', 'alg': 'HS256'}
        combo = {}
        currentTimestamp = int(time.time())
        data = {'iss': self.service_id, 'iat': currentTimestamp, 'exp': currentTimestamp + 30, 'jti': 'jwt_nonce'}
        combo.update(data)
        combo.update(header)
        encoded_jwt = jwt.encode(combo, self.api_key, algorithm='HS256')
        return encoded_jwt

    def report_status(
        self,
        response,
        start_time,
        name='email delivery time, async',
        context=None,
        message=None,
    ):
        events.request.fire(
            request_type=response.request.method,
            name=name,
            response_time=int((time.monotonic() - start_time) * 1000),
            response_length=len(response.content),
            response=response,
            context=context or {},
            exception=Exception(message) if message else None,
        )
        self.email_completed_counter = self.email_completed_counter + 1

        if self.email_completed_counter == self.email_limit:
            self.environment.runner.quit()

    def _async_send_email(
        self,
        timeout=600,
    ):
        notification_creation_response = self.client.post(
            '/v2/notifications/email',
            json={'template_id': self.email_template_id, 'email_address': 'test-email@not-a-real-email.com'},
            headers={'Authorization': f"Bearer {self._get_jwt().decode('utf-8')}"},
            verify=os.getenv('REQUESTS_CA_BUNDLE'),
        )

        if not notification_creation_response.ok:
            return

        notification_id = notification_creation_response.json()['id']

        start_time = time.monotonic()

        while time.monotonic() < start_time + timeout:
            notification_status_response = self.client.get(
                f'/v2/notifications/{notification_id}',
                headers={'Authorization': f"Bearer {self._get_jwt().decode('utf-8')}"},
                verify=os.getenv('REQUESTS_CA_BUNDLE'),
                name='notification status',
            )

            if notification_status_response.ok:
                notification_status = notification_status_response.json()['status']

                if notification_status == 'delivered':
                    self.report_status(start_time=start_time, response=notification_creation_response)
                    return

                elif notification_status in ['technical-failure', 'permanent-failure']:
                    self.report_status(
                        start_time=start_time,
                        response=notification_creation_response,
                        message=f'Failed - saw status {notification_status}',
                    )
                    return

            gevent.sleep(self.email_status_query_interval)

        self.report_status(
            start_time=start_time,
            response=notification_creation_response,
            message=f'Failed - timed out after {timeout} seconds',
        )

    @task
    def send_email_wrapper(self):
        gevent.spawn(self._async_send_email)
        self.email_triggered_counter += 1

        if self.email_triggered_counter == self.email_limit:
            self.environment.runner.stop()
