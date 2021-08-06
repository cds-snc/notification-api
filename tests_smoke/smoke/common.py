import csv
import itertools
import json
import os
import uuid
from enum import Enum
from io import StringIO
from typing import Any, List, Tuple

from boto3 import resource
from dotenv import load_dotenv
from notifications_utils.s3 import s3upload as utils_s3upload

load_dotenv()


class Config:
    API_HOST_NAME = os.environ.get("API_HOST_NAME")
    AWS_REGION = "ca-central-1"
    CSV_UPLOAD_BUCKET_NAME = os.environ.get("CSV_UPLOAD_BUCKET_NAME")
    ADMIN_CLIENT_USER_NAME = "notify-admin"
    ADMIN_CLIENT_SECRET = os.environ.get("ADMIN_CLIENT_SECRET")
    EMAIL_TO = os.environ.get("EMAIL_TO", "")
    SMS_TO = os.environ.get("SMS_TO", "")
    USER_ID = os.environ.get("USER_ID")
    SERVICE_ID = os.environ.get("SERVICE_ID", "")
    EMAIL_TEMPLATE_ID = os.environ.get("EMAIL_TEMPLATE_ID")
    SMS_TEMPLATE_ID = os.environ.get("SMS_TEMPLATE_ID")
    API_KEY = os.environ.get("API_KEY", "")


class Notification_type(Enum):
    EMAIL = "email"
    SMS = "sms"


def rows_to_csv(rows: List[List[str]]):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerows(rows)
    return output.getvalue()


def job_line(data: str, number_of_lines: int) -> List[List[str]]:
    return list(itertools.repeat([data, "test"], number_of_lines))


def pretty_print(data: Any):
    print(json.dumps(data, indent=4, sort_keys=True))


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
    s3 = resource("s3")
    return s3.Object(bucket_name, filename)
