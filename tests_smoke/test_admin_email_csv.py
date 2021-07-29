import os
import time

import requests
from dotenv import load_dotenv
from notifications_python_client.authentication import create_jwt_token

from .common import (
    job_line,
    pretty_print,
    rows_to_csv,
    s3upload,
    set_metadata_on_csv_upload,
)

load_dotenv()

API_KEY = os.environ.get("API_KEY")
EMAIL_TEMPLATE_ID = os.environ.get("EMAIL_TEMPLATE_ID")
USER_ID = os.environ.get("USER_ID")
SERVICE_ID = os.environ.get("SERVICE_ID")
ADMIN_CLIENT_SECRET = os.environ.get("ADMIN_CLIENT_SECRET")
ADMIN_CLIENT_USER_NAME = os.environ.get("ADMIN_CLIENT_USER_NAME")
EMAIL_TO = os.environ.get("EMAIL_TO")
API_HOST_NAME = os.environ.get("API_HOST_NAME")


def test_admin_email_csv():
    print("test_admin_email_csv... ", end="", flush=True)

    data = rows_to_csv([["email address", "name"], *job_line(EMAIL_TO, 1)])

    upload_id = s3upload(SERVICE_ID, data)
    metadata_kwargs = {
        "notification_count": 1,
        "template_id": str(EMAIL_TEMPLATE_ID),
        "valid": True,
        "original_file_name": "smoke_test.csv",
    }

    set_metadata_on_csv_upload(SERVICE_ID, upload_id, **metadata_kwargs)

    token = create_jwt_token(ADMIN_CLIENT_SECRET, client_id=ADMIN_CLIENT_USER_NAME)

    response = requests.post(
        f"{API_HOST_NAME}/service/{SERVICE_ID}/job",
        json={"id": upload_id, "created_by": USER_ID},
        headers={"Authorization": "Bearer {}".format(token)},
    )
    status_code = response.status_code
    body = response.json()

    if status_code != 201:
        print("FAILED: post to send_notification failed")
        pretty_print(body)
        return

    uri = f"{API_HOST_NAME}/service/{SERVICE_ID}/job/{upload_id}"

    for _ in range(20):
        time.sleep(1)
        response = requests.get(uri, headers={"Authorization": "Bearer {}".format(token)})
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
    test_admin_email_csv()
