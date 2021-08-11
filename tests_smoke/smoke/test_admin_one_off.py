import time

import requests
from notifications_python_client.authentication import create_jwt_token

from .common import Config, Notification_type, pretty_print


def test_admin_one_off(notification_type: Notification_type):
    print(f"test_admin_one_off ({notification_type.value})... ", end="", flush=True)

    token = create_jwt_token(Config.ADMIN_CLIENT_SECRET, client_id=Config.ADMIN_CLIENT_USER_NAME)
    to = Config.EMAIL_TO if notification_type == Notification_type.EMAIL else Config.SMS_TO
    template_id = Config.EMAIL_TEMPLATE_ID if notification_type == Notification_type.EMAIL else Config.SMS_TEMPLATE_ID

    response = requests.post(
        f"{Config.API_HOST_NAME}/service/{Config.SERVICE_ID}/send-notification",
        json={
            "to": to,
            "template_id": template_id,
            "created_by": Config.USER_ID,
            "personalisation": {"var": "var"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    status_code = response.status_code
    body = response.json()
    if status_code != 201:
        pretty_print(body)
        print("FAILED: post to send_notification failed")
        exit(1)

    notification_id = body["id"]
    for _ in range(20):
        time.sleep(1)
        response = requests.get(
            f"{Config.API_HOST_NAME}/service/{Config.SERVICE_ID}/notifications/{notification_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        status_code = response.status_code
        body = response.json()
        if body.get("status") in ["delivered", "permanent-failure"]:
            break

    if body.get("status") != "delivered":
        pretty_print(body)
        print("FAILED: email not sent successfully")
        exit(1)

    print("Success")
