import csv
import json
import os
import time

# from notifications_utils.s3 import s3upload as utils_s3upload
import urllib
import uuid
from enum import Enum
from io import StringIO
from typing import Any, Iterator, List, Tuple

import botocore
import requests
from boto3 import Session
from dotenv import load_dotenv
from notifications_python_client.authentication import create_jwt_token

load_dotenv()


class Config:
    API_HOST_NAME = os.environ.get("SMOKE_API_HOST_NAME")
    EMAIL_TO = os.environ.get("SMOKE_EMAIL_TO", "")
    SMS_TO = os.environ.get("SMOKE_SMS_TO", "")
    SERVICE_ID = os.environ.get("SMOKE_SERVICE_ID", "")
    EMAIL_TEMPLATE_ID = os.environ.get("SMOKE_EMAIL_TEMPLATE_ID")
    SMS_TEMPLATE_ID = os.environ.get("SMOKE_SMS_TEMPLATE_ID")

    USER_ID = os.environ.get("SMOKE_USER_ID")
    AWS_REGION = "ca-central-1"
    CSV_UPLOAD_BUCKET_NAME = os.environ.get("SMOKE_CSV_UPLOAD_BUCKET_NAME")
    ADMIN_CLIENT_USER_NAME = "notify-admin"
    ADMIN_CLIENT_SECRET = os.environ.get("SMOKE_ADMIN_CLIENT_SECRET")
    API_KEY = os.environ.get("SMOKE_API_KEY", "")
    POLL_TIMEOUT = int(os.environ.get("SMOKE_POLL_TIMEOUT", 20))


boto_session = Session(
    aws_access_key_id=os.environ.get("SMOKE_AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("SMOKE_AWS_SECRET_ACCESS_KEY"),
)


class Notification_type(Enum):
    EMAIL = "email"
    SMS = "sms"


class Attachment_type(Enum):
    NONE = "none"
    ATTACHED = "attach"
    LINK = "link"


def rows_to_csv(rows: List[List[str]]):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerows(rows)
    return output.getvalue()


def job_line(data: str, number_of_lines: int) -> Iterator[List[str]]:
    return map(lambda n: [data, f"var{n}"], range(0, number_of_lines))


def pretty_print(data: Any):
    print(json.dumps(data, indent=4, sort_keys=True))


def single_succeeded(uri: str, use_jwt: bool) -> bool:
    for n in range(Config.POLL_TIMEOUT):
        time.sleep(1)
        print(f"{n + 1} ", end="", flush=True)
        if use_jwt:
            token = create_jwt_token(Config.ADMIN_CLIENT_SECRET, client_id=Config.ADMIN_CLIENT_USER_NAME)
            headers = {"Authorization": f"Bearer {token}"}
        else:
            headers = {"Authorization": f"ApiKey-v1 {Config.API_KEY[-36:]}"}

        response = requests.get(
            uri,
            headers=headers,
        )
        body = response.json()
        success = body.get("status") == "delivered"
        failure = body.get("status") == "permanent-failure"
        if success or failure:
            break

    if not success:
        pretty_print(body)
    return success


def job_succeeded(service_id: str, job_id: str) -> bool:
    uri = f"{Config.API_HOST_NAME}/service/{service_id}/job/{job_id}"
    for n in range(Config.POLL_TIMEOUT):
        time.sleep(1)
        print(f"{n + 1} ", end="", flush=True)
        token = create_jwt_token(Config.ADMIN_CLIENT_SECRET, client_id=Config.ADMIN_CLIENT_USER_NAME)
        response = requests.get(uri, headers={"Authorization": f"Bearer {token}"})
        data = response.json()["data"]
        if data["job_status"] != "finished":
            next
        success = all([stat["status"] == "delivered" for stat in data["statistics"]])
        failure = any([stat["status"] == "permanent-failure" for stat in data["statistics"]])
        if success or failure:
            break

    if not success:
        pretty_print(data)
    return success


# from notifications_utils.s3 import s3upload as utils_s3upload
def utils_s3upload(filedata, region, bucket_name, file_location, content_type="binary/octet-stream", tags=None):
    _s3 = boto_session.resource("s3")

    key = _s3.Object(bucket_name, file_location)

    put_args = {"Body": filedata, "ServerSideEncryption": "AES256", "ContentType": content_type}

    if tags:
        tags = urllib.parse.urlencode(tags)
        put_args["Tagging"] = tags

    try:
        key.put(**put_args)
    except botocore.exceptions.ClientError as e:
        print("Unable to upload file to S3 bucket {}".format(bucket_name))
        raise e


# from admin app/s3_client/c3_csv_client.py

FILE_LOCATION_STRUCTURE = "service-{}-notify/{}.csv"


def get_csv_location(service_id: str, upload_id: str) -> Tuple[str, str]:
    if Config.CSV_UPLOAD_BUCKET_NAME:
        return (
            Config.CSV_UPLOAD_BUCKET_NAME,
            FILE_LOCATION_STRUCTURE.format(service_id, upload_id),
        )
    else:
        exit("CSV_UPLOAD_BUCKET_NAME undefined")


def s3upload(service_id: str, data: str) -> str:
    upload_id = str(uuid.uuid4())
    bucket_name, file_location = get_csv_location(service_id, upload_id)
    utils_s3upload(
        filedata=data,
        region=Config.AWS_REGION,
        bucket_name=bucket_name,
        file_location=file_location,
    )
    return upload_id


def set_metadata_on_csv_upload(service_id: str, upload_id: str, **kwargs):
    get_csv_upload(service_id, upload_id).copy_from(
        CopySource="{}/{}".format(*get_csv_location(service_id, upload_id)),
        ServerSideEncryption="AES256",
        Metadata={key: str(value) for key, value in kwargs.items()},
        MetadataDirective="REPLACE",
    )


def get_csv_upload(service_id: str, upload_id: str) -> Any:
    return get_s3_object(*get_csv_location(service_id, upload_id))


def get_s3_object(bucket_name: str, filename: str) -> Any:
    s3 = boto_session.resource("s3")
    return s3.Object(bucket_name, filename)
