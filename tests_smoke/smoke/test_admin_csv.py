import requests
from notifications_python_client.authentication import create_jwt_token

from .common import (
    Config,
    Notification_type,
    job_line,
    job_succeeded,
    pretty_print,
    rows_to_csv,
    s3upload,
    set_metadata_on_csv_upload,
)


def test_admin_csv(notification_type: Notification_type):
    print(f"test_admin_csv ({notification_type.value})... ", end="", flush=True)

    if notification_type == Notification_type.EMAIL:
        data = rows_to_csv([["email address", "var"], *job_line(Config.EMAIL_TO, 2)])
    else:
        data = rows_to_csv([["phone number", "var"], *job_line(Config.SMS_TO, 2)])

    upload_id = s3upload(Config.SERVICE_ID, data)
    metadata_kwargs = {
        "notification_count": 1,
        "template_id": Config.EMAIL_TEMPLATE_ID if notification_type == Notification_type.EMAIL else Config.SMS_TEMPLATE_ID,
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
    if response.status_code != 201:
        pretty_print(response.json)
        print("FAILED: post to send_notification failed")
        exit(1)

    success = job_succeeded(Config.SERVICE_ID, upload_id)
    if not success:
        print("FAILED: job didn't finish successfully")
        exit(1)
    print("Success")
