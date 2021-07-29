from common import pretty_print
from dotenv import load_dotenv
import os
import requests
import time

load_dotenv()

API_KEY = os.environ.get("API_KEY")
SMS_TEMPLATE_ID = os.environ.get("SMS_TEMPLATE_ID")
SMS_TO = os.environ.get("SMS_TO")
API_HOST_NAME = os.environ.get("API_HOST_NAME")


def test_api_sms():
    print("test_api_sms... ", end="", flush=True)
    response = requests.post(
        f"{API_HOST_NAME}/v2/notifications/sms",
        json={
            "phone_number": SMS_TO,
            "template_id": SMS_TEMPLATE_ID,
        },
        headers={"Authorization": f"ApiKey-v1 {API_KEY[-36:]}"},
    )
    if response.status_code != 201:
        print("FAILED: post to v2/notifications/sms failed")
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
        print("FAILED: sms not sent successfully")
        pretty_print(response.json())
        return

    print("Success")


if __name__ == "__main__":
    test_api_sms()
