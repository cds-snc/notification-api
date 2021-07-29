import os
import time

import requests
from dotenv import load_dotenv
from notifications_python_client.authentication import create_jwt_token

from .common import pretty_print

load_dotenv()

API_KEY = os.environ.get("API_KEY")
EMAIL_TEMPLATE_ID = os.environ.get("EMAIL_TEMPLATE_ID")
USER_ID = os.environ.get("USER_ID")
SERVICE_ID = os.environ.get("SERVICE_ID")
ADMIN_CLIENT_SECRET = os.environ.get("ADMIN_CLIENT_SECRET")
ADMIN_CLIENT_USER_NAME = os.environ.get("ADMIN_CLIENT_USER_NAME")
EMAIL_TO = os.environ.get("EMAIL_TO")
API_HOST_NAME = os.environ.get("API_HOST_NAME")


def test_admin_email_one_off():
    print("test_admin_email_one_off... ", end="", flush=True)

    token = create_jwt_token(ADMIN_CLIENT_SECRET, client_id=ADMIN_CLIENT_USER_NAME)

    response = requests.post(
        f"{API_HOST_NAME}/service/{SERVICE_ID}/send-notification",
        json={"to": EMAIL_TO, "template_id": EMAIL_TEMPLATE_ID, "created_by": USER_ID},
        headers={"Authorization": "Bearer {}".format(token)},
    )
    status_code = response.status_code
    body = response.json()
    if status_code != 201:
        print("FAILED: post to send_notification failed")
        pretty_print(body)
        return

    notification_id = body["id"]
    for _ in range(20):
        time.sleep(1)
        response = requests.get(
            f"{API_HOST_NAME}/service/{SERVICE_ID}/notifications/{notification_id}",
            headers={"Authorization": "Bearer {}".format(token)},
        )
        status_code = response.status_code
        body = response.json()
        if status_code != 200:
            print("FAILED: couldn't get notification status")
            pretty_print(body)
            return
        if body["status"] == "sending" or body["status"] == "delivered":
            break

    if body["status"] != "sending" and body["status"] != "delivered":
        print("FAILED: email not sent successfully")
        pretty_print(body)
        return
    print("Success")


if __name__ == "__main__":
    test_admin_email_one_off()
