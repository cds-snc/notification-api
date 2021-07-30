import time
from datetime import datetime

import requests
from common import Config, job_line, pretty_print, rows_to_csv  # type: ignore
from notifications_python_client.authentication import create_jwt_token


def test_api_bulk(notification_type: str):
    print(f"test_api_bulk ({notification_type})... ", end="", flush=True)
    template_id = Config.EMAIL_TEMPLATE_ID if notification_type == "email" else Config.SMS_TEMPLATE_ID
    to = Config.EMAIL_TO if notification_type == "email" else Config.SMS_TO
    header = "email address" if notification_type == "email" else "phone number"

    response = requests.post(
        f"{Config.API_HOST_NAME}/v2/notifications/bulk",
        json={
            "name": f"My bulk name {datetime.utcnow().isoformat()}",
            "template_id": template_id,
            "csv": rows_to_csv([[header, "name"], *job_line(to, 1)]),
        },
        headers={"Authorization": f"ApiKey-v1 {Config.API_KEY[-36:]}"},
    )

    if response.status_code != 201:
        print("FAILED: post failed")
        pretty_print(response.json())
        return

    service_id = response.json()["data"]["service"]
    job_id = response.json()["data"]["id"]
    uri = f"{Config.API_HOST_NAME}/service/{service_id}/job/{job_id}"
    token = create_jwt_token(Config.ADMIN_CLIENT_SECRET, client_id=Config.ADMIN_CLIENT_USER_NAME)

    for _ in range(20):
        time.sleep(1)
        response = requests.get(uri, headers={"Authorization": f"Bearer {token}"})
        status_code = response.status_code
        data = response.json()["data"]
        if (
            status_code == 200 and data.get("job_status") == "finished"
        ):  # I don't think this is correct - we should check the notification status
            break

    if status_code != 200 or data.get("job_status") != "finished":
        print("FAILED: job didn't finish successfully")
        pretty_print(response.json())
        return

    print("Success")


if __name__ == "__main__":
    test_api_bulk("email")
    test_api_bulk("sms")
