"""
Code to keep the lambda function alive.
"""
import os

from notifications_python_client.notifications import NotificationsAPIClient

API_KEY = os.getenv("HEARTBEAT_API_KEY")
BASE_URL = "https://api.notification.canada.ca"
EMAIL_ADDRESS = "success@simulator.amazonses.com"
TEMPLATE_ID = "7daa4f22-633b-4a7b-8b20-dfc5f66882bd"

notifications_client = NotificationsAPIClient(API_KEY, base_url=BASE_URL)

if __name__ == "__main__":
    response = notifications_client.send_email_notification(email_address=EMAIL_ADDRESS, template_id=TEMPLATE_ID)
