import requests

from .common import Config, Notification_type, pretty_print, single_succeeded


def test_api_one_off(notification_type: Notification_type):
    print(f"test_api_oneoff ({notification_type.value})... ", end="", flush=True)

    if notification_type == Notification_type.EMAIL:
        data = {
            "email_address": Config.EMAIL_TO,
            "template_id": Config.EMAIL_TEMPLATE_ID,
            "personalisation": {"var": "var"},
        }
    else:
        data = {
            "phone_number": Config.SMS_TO,
            "template_id": Config.SMS_TEMPLATE_ID,
            "personalisation": {"var": "var"},
        }

    response = requests.post(
        f"{Config.API_HOST_NAME}/v2/notifications/{notification_type.value}",
        json=data,
        headers={"Authorization": f"ApiKey-v1 {Config.API_KEY[-36:]}"},
    )
    if response.status_code != 201:
        pretty_print(response.json())
        print(f"FAILED: post to v2/notifications/{notification_type.value} failed")
        exit(1)

    uri = response.json()["uri"]

    success = single_succeeded(uri, use_jwt=False)
    if not success:
        print("FAILED: job didn't finish successfully")
        exit(1)
    print("Success")
