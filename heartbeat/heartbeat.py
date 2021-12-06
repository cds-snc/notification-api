"""
Code to keep the lambda function alive.
"""
import os
import uuid

from notifications_python_client.notifications import NotificationsAPIClient

API_KEY: str = os.getenv("TF_VAR_heartbeat_api_key")
# BASE_URL is a list of api urls - k8s and lambda.
BASE_URL: [] = os.getenv("TF_VAR_heartbeat_base_url")
EMAIL_ADDRESS = "success@simulator.amazonses.com"
TEMPLATE_ID: uuid.UUID = os.getenv("TF_VAR_heartbeat_template_id")

if __name__ == "__main__":
    if not BASE_URL:
        print("Variable BASE_URL is missing")
    if not API_KEY:
        print("Variable API_KEY is missing")
    if not TEMPLATE_ID:
        print("Variable TEMPLATE_ID is missing")
    for base_url in BASE_URL:
        notifications_client = NotificationsAPIClient(API_KEY, base_url=base_url)
        response = notifications_client.send_email_notification(email_address=EMAIL_ADDRESS, template_id=TEMPLATE_ID)
