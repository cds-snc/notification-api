"""
Code to keep the lambda API alive.
"""
import ast
import os
import uuid
from typing import List

from notifications_python_client.errors import HTTPError
from notifications_python_client.notifications import NotificationsAPIClient

API_KEY: str = os.getenv("heartbeat_api_key", "")
# As we can't pass in a list to env var, we pass a str and convert it.
BASE_URL: List[str] = ast.literal_eval(os.getenv("heartbeat_base_url"))  # type: ignore
EMAIL_ADDRESS = "success@simulator.amazonses.com"
TEMPLATE_ID: uuid.UUID = os.getenv("heartbeat_template_id")  # type: ignore


def handler(event, context):
    if not BASE_URL:
        print("Variable BASE_URL is missing")
    if not API_KEY:
        print("Variable API_KEY is missing")
    if not TEMPLATE_ID:
        print("Variable TEMPLATE_ID is missing")
    for base_url in BASE_URL:
        notifications_client = NotificationsAPIClient(API_KEY, base_url=base_url)
        try:
            notifications_client.send_email_notification(email_address=EMAIL_ADDRESS, template_id=TEMPLATE_ID)
            print("Email has been sent by {}!".format(base_url))
        except HTTPError as e:
            print(f"Could not send heartbeat: status={e.status_code}, msg={e.message}")
            raise
