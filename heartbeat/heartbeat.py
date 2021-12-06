"""
Code to keep the lambda function alive.
"""
import os

from notifications_python_client.notifications import NotificationsAPIClient

API_KEY = os.getenv("TF_VAR_heartbeat_api_key")
BASE_URL = os.getenv("TF_VAR_base_url")
EMAIL_ADDRESS = "success@simulator.amazonses.com"
TEMPLATE_ID = os.getenv("TF_VAR_template_id")

notifications_client = NotificationsAPIClient(API_KEY, base_url=BASE_URL)

if __name__ == "__main__":
    response = notifications_client.send_email_notification(email_address=EMAIL_ADDRESS, template_id=TEMPLATE_ID)
