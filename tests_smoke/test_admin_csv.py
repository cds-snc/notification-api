import time

import requests
from common import (  # type: ignore
    Config,
    job_line,
    pretty_print,
    rows_to_csv,
    s3upload,
    set_metadata_on_csv_upload,
)
from notifications_python_client.authentication import create_jwt_token


def test_admin_csv(notification_type: str):
    print(f"test_admin_csv ({notification_type})... ", end="", flush=True)

    if notification_type == "email":
        data = rows_to_csv([["email address", "name"], *job_line(Config.EMAIL_TO, 1)])
    else:
        data = rows_to_csv([["phone number", "name"], *job_line(Config.SMS_TO, 1)])

    upload_id = s3upload(Config.SERVICE_ID, data)
    metadata_kwargs = {
        "notification_count": 1,
        "template_id": Config.EMAIL_TEMPLATE_ID if notification_type == "email" else Config.SMS_TEMPLATE_ID,
        "valid": True,
        "original_file_name": "smoke_test.csv",
    }

    set_metadata_on_csv_upload(Config.SERVICE_ID, upload_id, **metadata_kwargs)

    token = create_jwt_token(Config.ADMIN_CLIENT_SECRET, client_id=Config.ADMIN_CLIENT_USER_NAME)

    response = requests.post(
        f"{Config.API_HOST_NAME}/service/{Config.SERVICE_ID}/job",
        json={"id": upload_id, "created_by": Config.USER_ID},
        headers={"Authorization": f"Bearer {token}"},
    )
    status_code = response.status_code
    body = response.json()

    if status_code != 201:
        print("FAILED: post to send_notification failed")
        pretty_print(body)
        return

    uri = f"{Config.API_HOST_NAME}/service/{Config.SERVICE_ID}/job/{upload_id}"

    for _ in range(20):
        time.sleep(1)
        response = requests.get(uri, headers={"Authorization": f"Bearer {token}"})
        status_code = response.status_code
        data = response.json()["data"]
        if status_code == 200 and data.get("job_status") == "finished":
            break

    if status_code != 200 or data.get("job_status") != "finished":
        print("FAILED: job didn't finish successfully")
        pretty_print(response.json())
        return

    print("Success")


if __name__ == "__main__":
    test_admin_csv("email")
    test_admin_csv("sms")
