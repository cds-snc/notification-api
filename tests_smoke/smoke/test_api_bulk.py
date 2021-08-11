from datetime import datetime

import requests

from .common import (
    Config,
    Notification_type,
    job_line,
    job_succeeded,
    pretty_print,
    rows_to_csv,
)


def test_api_bulk(notification_type: Notification_type):
    print(f"test_api_bulk ({notification_type.value})... ", end="", flush=True)
    template_id = Config.EMAIL_TEMPLATE_ID if notification_type == Notification_type.EMAIL else Config.SMS_TEMPLATE_ID
    to = Config.EMAIL_TO if notification_type == Notification_type.EMAIL else Config.SMS_TO
    header = "email address" if notification_type == Notification_type.EMAIL else "phone number"

    response = requests.post(
        f"{Config.API_HOST_NAME}/v2/notifications/bulk",
        json={
            "name": f"My bulk name {datetime.utcnow().isoformat()}",
            "template_id": template_id,
            "csv": rows_to_csv([[header, "var"], *job_line(to, 2)]),
        },
        headers={"Authorization": f"ApiKey-v1 {Config.API_KEY[-36:]}"},
    )
    if response.status_code != 201:
        pretty_print(response.json())
        print("FAILED: post failed")
        exit(1)

    success = job_succeeded(Config.SERVICE_ID, response.json()["data"]["id"])
    if not success:
        print("FAILED: job didn't finish successfully")
        exit(1)
    print("Success")
