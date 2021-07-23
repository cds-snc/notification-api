from dotenv import load_dotenv
import json
from notifications_python_client.authentication import create_jwt_token
import os
import requests
import time
import uuid


# 127.0.0.1 - - [20/Jul/2021 16:27:52] "POST /service/a4d0638a-d06b-4971-9346-2f584f5b4ad5/job HTTP/1.1" 201 -
# POST /services/a4d0638a-d06b-4971-9346-2f584f5b4ad5/start-job/1c152e8f-a39a-45ae-9af9-cf0e4f368abc?original_file_name=staging_email2.csv
# POST /services/a4d0638a-d06b-4971-9346-2f584f5b4ad5/send/42958d1d-39f2-4aa4-a856-7ed3c165820f/csv

load_dotenv()

API_KEY = os.environ.get("API_KEY")
TEMPLATE_ID = os.environ.get("TEMPLATE_ID")
USER_ID = os.environ.get("USER_ID")
SERVICE_ID = os.environ.get("SERVICE_ID")
ADMIN_CLIENT_SECRET = os.environ.get("ADMIN_CLIENT_SECRET")
ADMIN_CLIENT_USER_NAME = os.environ.get("ADMIN_CLIENT_USER_NAME")
EMAIL_SEND_TO = os.environ.get("EMAIL_SEND_TO")


def pretty_print(data):
    print(json.dumps(data, indent=4, sort_keys=True))


def test_admin_email_csv():
    print("test_admin_csv... ", end="", flush=True)

    token = create_jwt_token(ADMIN_CLIENT_SECRET, client_id=ADMIN_CLIENT_USER_NAME)

    response = requests.post(
        f"http://localhost:6011/services/{SERVICE_ID}/send/{TEMPLATE_ID}/csv",
        json={},
        headers={"Authorization": "Bearer {}".format(token)},
    )

    status_code = response.status_code
    body = response.json()
    pretty_print(body)

    if status_code != 201:
        print("FAILED: post to send_notification failed")
        pretty_print(body)
        return

    notification_id = body["id"]
    for _ in range(20):
        time.sleep(1)
        response = requests.get(
            f"http://localhost:6011/service/{SERVICE_ID}/notifications/{notification_id}",
            headers={"Authorization": "Bearer {}".format(token)},
        )
        status_code = response.status_code
        body = response.json()
        if status_code != 200:
            print("FAILED: couldn't get notification status")
            pretty_print(body)
            return
        if body["status"] == "sending":
            break

    if body["status"] != "sending":
        print("FAILED: email not sent successfully")
        pretty_print(body)
        return
    print("Success")


if __name__ == "__main__":
    test_admin_email_csv()
