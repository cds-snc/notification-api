import os
import time
from datetime import datetime

import requests
from common import pretty_print
from dotenv import load_dotenv
from notifications_python_client.authentication import create_jwt_token

load_dotenv()

API_KEY = os.environ.get("API_KEY")
SMS_TEMPLATE_ID = os.environ.get("SMS_TEMPLATE_ID")
ADMIN_CLIENT_SECRET = os.environ.get("ADMIN_CLIENT_SECRET")
ADMIN_CLIENT_USER_NAME = os.environ.get("ADMIN_CLIENT_USER_NAME")
SMS_TO = os.environ.get("SMS_TO")
API_HOST_NAME = os.environ.get("API_HOST_NAME")


def test_api_sms_bulk():
    print("test_api_sms_bulk... ", end="", flush=True)
    response = requests.post(
        f"{API_HOST_NAME}/v2/notifications/bulk",
        json={
            "name": f"Smoke api sms bulk {datetime.utcnow().isoformat()}",
            "template_id": SMS_TEMPLATE_ID,
            "rows": [["phone number"], [SMS_TO]],
        },
        headers={"Authorization": f"ApiKey-v1 {API_KEY[-36:]}"},
    )
    if response.status_code != 201:
        print("FAILED: post failed")
        pretty_print(response.json())
        return

    service_id = response.json()["data"]["service"]
    job_id = response.json()["data"]["id"]
    uri = f"{API_HOST_NAME}/service/{service_id}/job/{job_id}"
    token = create_jwt_token(ADMIN_CLIENT_SECRET, client_id=ADMIN_CLIENT_USER_NAME)

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
    test_api_sms_bulk()
