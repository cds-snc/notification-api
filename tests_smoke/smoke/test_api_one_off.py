import time

import requests

from .common import Config, Notification_type, pretty_print


def test_api_one_off(notification_type: Notification_type):
    print(f"test_api_oneoff ({notification_type.value})... ", end="", flush=True)

    if notification_type == Notification_type.EMAIL:
        data = {
            "email_address": Config.EMAIL_TO,
            "template_id": Config.EMAIL_TEMPLATE_ID,
        }
    else:
        data = {
            "phone_number": Config.SMS_TO,
            "template_id": Config.SMS_TEMPLATE_ID,
        }

    response = requests.post(
        f"{Config.API_HOST_NAME}/v2/notifications/{notification_type.value}",
        json=data,
        headers={"Authorization": f"ApiKey-v1 {Config.API_KEY[-36:]}"},
    )
    if response.status_code != 201:
        print(f"FAILED: post to v2/notifications/{notification_type.value} failed")
        pretty_print(response.json())
        return

    uri = response.json()["uri"]

    for _ in range(20):
        time.sleep(1)
        response = requests.get(
            uri,
            headers={"Authorization": f"ApiKey-v1 {Config.API_KEY[-36:]}"},
        )
        if response.status_code == 200:
            break

    if response.status_code != 200:
        print("FAILED: email not sent successfully")
        pretty_print(response.json())
        return

    print("Success")
