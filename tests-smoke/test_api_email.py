import csv
from datetime import datetime
from dotenv import load_dotenv
from io import StringIO
import itertools
import json
import os
import requests


load_dotenv()

API_KEY = os.environ.get("API_KEY")
TEMPLATE_ID = os.environ.get("TEMPLATE_ID")


def pretty_print(data):
    print(json.dumps(data, indent=4, sort_keys=True))


def test_api_email():
    print("test_api_email... ", end="", flush=True)
    response = requests.post(
        "http://localhost:6011/v2/notifications/email",
        json={
            "email_address": "success@simulator.amazonses.com",
            "template_id": TEMPLATE_ID,
        },
        headers={"Authorization": f"ApiKey-v1 {API_KEY[-36:]}"},
    )
    if response.status_code != 201:
        print("FAILED: post to v2/notifications/email failed")
        pretty_print(response.json())
        return

    uri = response.json()["uri"]
    response = requests.get(
        uri,
        headers={"Authorization": f"ApiKey-v1 {API_KEY[-36:]}"},
    )
    if response.status_code != 200:
        print("FAILED: email not sent successfully")
        pretty_print(response.json())
        return

    print("Success")


if __name__ == "__main__":
    test_api_email()
