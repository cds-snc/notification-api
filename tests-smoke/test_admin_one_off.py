import csv
from datetime import datetime
from dotenv import load_dotenv
from io import StringIO
import itertools
import json
import os
import requests
from notifications_python_client.authentication import create_jwt_token


load_dotenv()

API_KEY = os.environ.get("API_KEY")
TEMPLATE_ID = os.environ.get("TEMPLATE_ID")
USER_ID = os.environ.get("USER_ID")
SERVICE_ID = os.environ.get("SERVICE_ID")
ADMIN_CLIENT_SECRET = os.environ.get("ADMIN_CLIENT_SECRET")
ADMIN_CLIENT_USER_NAME = os.environ.get("ADMIN_CLIENT_USER_NAME")


def pretty_print(data):
    print(json.dumps(data, indent=4, sort_keys=True))


def test_admin_one_off():
    print("test_admin_one_off... ", end="", flush=True)

    token = create_jwt_token(ADMIN_CLIENT_SECRET, client_id=ADMIN_CLIENT_USER_NAME)

    response = requests.post(
        f"http://localhost:6011//service/{SERVICE_ID}/send-notification",
        json={"to": "success@simulator.amazonses.com", "template_id": TEMPLATE_ID, "created_by": USER_ID},
        headers={"Authorization": "Bearer {}".format(token)},
    )
    if response.status_code != 201:
        print("FAILED: post to send_notification failed")
        pretty_print(response.json())
        return

    pretty_print(response.json())
    notification_id = response.json["id"]
    response = requests.get(
        f"http://localhost:6011//notification/{notification_id}",
        headers={"Authorization": "Bearer {}".format(token)},
    )
    if response.status_code != 200:
        print("FAILED: email not sent successfully")
        pretty_print(response.json())
        return

    print("Success")


if __name__ == "__main__":
    test_admin_one_off()
