from common import pretty_print
from dotenv import load_dotenv
import json
import os
import requests
import time

load_dotenv()

API_KEY = os.environ.get("API_KEY")
EMAIL_TEMPLATE_ID = os.environ.get("EMAIL_TEMPLATE_ID")
EMAIL_TO = os.environ.get("EMAIL_TO")
API_HOST_NAME = os.environ.get("API_HOST_NAME")


def test_api_email():
    print("test_api_email... ", end="", flush=True)
    response = requests.post(
        f"{API_HOST_NAME}/v2/notifications/email",
        json={
            "email_address": EMAIL_TO,
            "template_id": EMAIL_TEMPLATE_ID,
        },
        headers={"Authorization": f"ApiKey-v1 {API_KEY[-36:]}"},
    )
    if response.status_code != 201:
        print("FAILED: post to v2/notifications/email failed")
        pretty_print(response.json())
        return

    uri = response.json()["uri"]

    for _ in range(20):
        time.sleep(1)
        response = requests.get(
            uri,
            headers={"Authorization": f"ApiKey-v1 {API_KEY[-36:]}"},
        )
        if response.status_code == 200:
            break

    if response.status_code != 200:
        print("FAILED: email not sent successfully")
        pretty_print(response.json())
        return

    print("Success")


if __name__ == "__main__":
    test_api_email()
