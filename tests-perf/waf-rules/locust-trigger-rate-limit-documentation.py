"""locust-trigger-rate-limit.py

Trigger rate limit on our WAF rules on the following endpoints:

* Sign-in
* Register
* forgot password
* forced password reset

Once the necessary rate limit has been attained within a 5 minutes period, the
tests will start to fail as expected.
"""
# flake8: noqa

from locust import HttpUser, constant_pacing, task


class NotifyDocumentationUser(HttpUser):

    host = "https://documentation.notification.canada.ca/"
    spawn_rate = 10
    wait_time = constant_pacing(1)

    def __init__(self, *args, **kwargs):
        super(NotifyDocumentationUser, self).__init__(*args, **kwargs)
        self.headers = {}

    @task(1)
    def trigger_home_block(self):
        self.client.get("/", headers=self.headers)
