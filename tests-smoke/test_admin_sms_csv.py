import csv

from dotenv import load_dotenv
from io import StringIO
import itertools
import json
from notifications_python_client.authentication import create_jwt_token
import os
from notifications_utils.s3 import s3upload as utils_s3upload
import requests
import time
import uuid
from boto3 import resource

# NOTE: this doesn't work yet


load_dotenv()

API_KEY = os.environ.get("API_KEY")
SMS_TEMPLATE_ID = os.environ.get("SMS_TEMPLATE_ID")
USER_ID = os.environ.get("USER_ID")
SERVICE_ID = os.environ.get("SERVICE_ID")
ADMIN_CLIENT_SECRET = os.environ.get("ADMIN_CLIENT_SECRET")
ADMIN_CLIENT_USER_NAME = os.environ.get("ADMIN_CLIENT_USER_NAME")
SMS_TO = os.environ.get("SMS_TO")
API_HOST_NAME = os.environ.get("API_HOST_NAME")
CSV_UPLOAD_BUCKET_NAME = os.environ.get("CSV_UPLOAD_BUCKET_NAME")
AWS_REGION = os.environ.get("AWS_REGION")


def rows_to_csv(rows):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerows(rows)
    return output.getvalue()


def job_line(number_of_lines):
    return list(itertools.repeat([SMS_TO, "test"], number_of_lines))


# from admin app/s3_client/c3_csv_client.py ---------

FILE_LOCATION_STRUCTURE = "service-{}-notify/{}.csv"


def get_csv_location(service_id, upload_id):
    return (
        CSV_UPLOAD_BUCKET_NAME,
        FILE_LOCATION_STRUCTURE.format(service_id, upload_id),
    )


def s3upload(service_id, data):
    upload_id = str(uuid.uuid4())
    bucket_name, file_location = get_csv_location(service_id, upload_id)
    utils_s3upload(
        filedata=data,
        region=AWS_REGION,
        bucket_name=bucket_name,
        file_location=file_location,
    )
    return upload_id


def set_metadata_on_csv_upload(service_id, upload_id, **kwargs):
    get_csv_upload(service_id, upload_id).copy_from(
        CopySource="{}/{}".format(*get_csv_location(service_id, upload_id)),
        ServerSideEncryption="AES256",
        Metadata={key: str(value) for key, value in kwargs.items()},
        MetadataDirective="REPLACE",
    )


def get_csv_upload(service_id, upload_id):
    return get_s3_object(*get_csv_location(service_id, upload_id))


def get_s3_object(bucket_name, filename):
    s3 = resource("s3")
    return s3.Object(bucket_name, filename)


# --------------------------------------------------


def pretty_print(data):
    print(json.dumps(data, indent=4, sort_keys=True))


def test_admin_email_csv():
    print("test_admin_csv... ", end="", flush=True)

    data = rows_to_csv([["phone number", "name"], *job_line(1)])

    upload_id = s3upload(SERVICE_ID, data)
    metadata_kwargs = {
        "notification_count": 1,
        "template_id": str(SMS_TEMPLATE_ID),
        "valid": True,
        "original_file_name": "smoke_test.csv",
    }

    set_metadata_on_csv_upload(SERVICE_ID, upload_id, **metadata_kwargs)

    print(f"upload id: {upload_id}")
    print(f"file: {get_csv_location(SERVICE_ID, upload_id)}")

    token = create_jwt_token(ADMIN_CLIENT_SECRET, client_id=ADMIN_CLIENT_USER_NAME)

    response = requests.post(
        f"{API_HOST_NAME}/service/{SERVICE_ID}/job",
        json={"id": upload_id, "created_by": USER_ID},
        headers={"Authorization": "Bearer {}".format(token)},
    )
    status_code = response.status_code
    body = response.json()

    print(f"status: {status_code}")
    pretty_print(body)

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
