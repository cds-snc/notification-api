import uuid
from datetime import datetime, timedelta
from typing import List

import botocore
import pytz
from boto3 import client, resource
from flask import current_app
from notifications_utils.s3 import s3upload as utils_s3upload

from app.models import Job

FILE_LOCATION_STRUCTURE = "service-{}-notify/{}.csv"
REPORTS_FILE_LOCATION_STRUCTURE = "service-{}/{}.csv"
THREE_DAYS_IN_SECONDS = 3 * 24 * 60 * 60


def get_s3_file(bucket_name, file_location):
    s3_file = get_s3_object(bucket_name, file_location)
    return s3_file.get()["Body"].read().decode("utf-8")


def get_s3_object(bucket_name, file_location):
    s3 = resource("s3")
    return s3.Object(bucket_name, file_location)


def file_exists(bucket_name, file_location):
    try:
        # try and access metadata of object
        get_s3_object(bucket_name, file_location).metadata
        return True
    except botocore.exceptions.ClientError as e:
        if e.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
            return False
        raise


def get_job_location(service_id, job_id):
    return (
        current_app.config["CSV_UPLOAD_BUCKET_NAME"],
        FILE_LOCATION_STRUCTURE.format(service_id, job_id),
    )


def upload_job_to_s3(service_id, file_data):
    upload_id = str(uuid.uuid4())
    bucket, location = get_job_location(service_id, upload_id)
    utils_s3upload(
        filedata=file_data,
        region=current_app.config["AWS_REGION"],
        bucket_name=bucket,
        file_location=location,
    )
    return upload_id


def get_job_from_s3(service_id, job_id):
    obj = get_s3_object(*get_job_location(service_id, job_id))
    return obj.get()["Body"].read().decode("utf-8")


def get_job_metadata_from_s3(service_id, job_id):
    obj = get_s3_object(*get_job_location(service_id, job_id))
    return obj.get()["Metadata"]


def remove_jobs_from_s3(jobs: List[Job], batch_size=1000):
    """
    Remove the files from S3 for the given jobs.

    Args:
        jobs (List[Job]): The jobs whose files need to be removed from S3.
        batch_size (int, optional): The number of jobs to process in each boto call. Defaults to the AWS maximum of 1000.
    """

    bucket = resource("s3").Bucket(current_app.config["CSV_UPLOAD_BUCKET_NAME"])

    for start in range(0, len(jobs), batch_size):
        object_keys = [FILE_LOCATION_STRUCTURE.format(job.service_id, job.id) for job in jobs[start : start + batch_size]]
        bucket.delete_objects(Delete={"Objects": [{"Key": key} for key in object_keys]})


def get_s3_bucket_objects(bucket_name, subfolder="", older_than=7, limit_days=2):
    boto_client = client("s3", current_app.config["AWS_REGION"])
    paginator = boto_client.get_paginator("list_objects_v2")
    page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=subfolder)

    all_objects_in_bucket = []
    for page in page_iterator:
        if page.get("Contents"):
            all_objects_in_bucket.extend(page["Contents"])

    return all_objects_in_bucket


def filter_s3_bucket_objects_within_date_range(bucket_objects, older_than=7, limit_days=2):
    """
    S3 returns the Object['LastModified'] as an 'offset-aware' timestamp so the
    date range filter must take this into account.

    Additionally an additional Object is returned by S3 corresponding to the
    container directory. This is redundant and should be removed.

    """
    end_date = datetime.now(tz=pytz.utc) - timedelta(days=older_than)
    start_date = end_date - timedelta(days=limit_days)
    filtered_items = [
        item
        for item in bucket_objects
        if all(
            [
                not item["Key"].endswith("/"),
                item["LastModified"] > start_date,
                item["LastModified"] < end_date,
            ]
        )
    ]

    return filtered_items


def remove_s3_object(bucket_name, object_key):
    obj = get_s3_object(bucket_name, object_key)
    return obj.delete()


def remove_transformed_dvla_file(job_id):
    bucket_name = current_app.config["DVLA_BUCKETS"]["job"]
    file_location = "{}-dvla-job.text".format(job_id)
    obj = get_s3_object(bucket_name, file_location)
    return obj.delete()


def get_list_of_files_by_suffix(bucket_name, subfolder="", suffix="", last_modified=None):
    s3_client = client("s3", current_app.config["AWS_REGION"])
    paginator = s3_client.get_paginator("list_objects_v2")

    page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=subfolder)

    for page in page_iterator:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith(suffix.lower()):
                if not last_modified or obj["LastModified"] >= last_modified:
                    yield key


def get_report_location(service_id, report_id):
    return REPORTS_FILE_LOCATION_STRUCTURE.format(service_id, report_id)


def upload_report_to_s3(service_id: str, report_id: str, file_data: bytes) -> str:
    object_key = get_report_location(service_id, report_id)
    utils_s3upload(
        filedata=file_data,
        region=current_app.config["AWS_REGION"],
        bucket_name=current_app.config["REPORTS_BUCKET_NAME"],
        file_location=object_key,
    )
    url = generate_presigned_url(
        bucket_name=current_app.config["REPORTS_BUCKET_NAME"],
        object_key=object_key,
        expiration=THREE_DAYS_IN_SECONDS,
    )
    return url


def generate_presigned_url(bucket_name: str, object_key: str, expiration: int = 3600) -> str:
    """
    Generate a presigned URL to share an S3 object

    :param bucket_name: string
    :param object_key: string
    :param expiration: Time in seconds for the presigned URL to remain valid
    :return: Presigned URL as string. If error, returns None.

    Docs: https://docs.aws.amazon.com/AmazonS3/latest/userguide/ShareObjectPreSignedURL.html
    """
    s3_client = client("s3", current_app.config["AWS_REGION"])
    try:
        response = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": object_key},
            ExpiresIn=expiration,
        )
    except botocore.exceptions.ClientError as e:
        current_app.logger.error(e)
        return ""

    return response


def upload_report_to_s3_multipart(service_id: str, report_id: str, file_generator) -> str:
    """
    Uploads a report to S3 using either regular or multipart uploads based on file size.
    Takes a generator that yields chunks of the file.

    :param service_id: The service ID
    :param report_id: The report ID
    :param file_generator: Generator that yields chunks of file data
    :return: Presigned URL for the uploaded file
    """
    object_key = get_report_location(service_id, report_id)
    bucket_name = current_app.config["REPORTS_BUCKET_NAME"]
    region = current_app.config["AWS_REGION"]
    s3_client = client("s3", region)

    # Buffer smaller files in memory first to determine if multipart is needed
    # AWS requires each part (except the final one) to be at least 5MB
    MIN_PART_SIZE = 5 * 1024 * 1024  # 5MB in bytes
    REGULAR_UPLOAD_THRESHOLD = 10 * 1024 * 1024  # 10MB threshold for regular upload

    # Try reading all content to determine size
    buffer = []
    total_size = 0

    for chunk in file_generator:
        buffer.append(chunk)
        total_size += len(chunk.encode("utf-8") if isinstance(chunk, str) else chunk)

    # If the total file is small, use regular upload
    if total_size < REGULAR_UPLOAD_THRESHOLD:
        current_app.logger.info(f"Using regular upload for small report: {report_id}, size: {total_size} bytes")
        complete_data = b"".join([chunk.encode("utf-8") if isinstance(chunk, str) else chunk for chunk in buffer])

        # Use regular upload
        s3_client.put_object(Bucket=bucket_name, Key=object_key, Body=complete_data, ContentType="text/csv")
    else:
        current_app.logger.info(f"Using multipart upload for large report: {report_id}, size: {total_size} bytes")
        # Create multipart upload
        mpu = s3_client.create_multipart_upload(Bucket=bucket_name, Key=object_key, ContentType="text/csv")

        upload_id = mpu["UploadId"]
        parts = []

        try:
            # Process the buffered data into properly sized parts
            current_part = b""
            part_number = 1

            # Process initial buffer first
            for chunk in buffer:
                chunk_data = chunk.encode("utf-8") if isinstance(chunk, str) else chunk
                current_part += chunk_data

                # If part is big enough, upload it
                if len(current_part) >= MIN_PART_SIZE:
                    part = s3_client.upload_part(
                        Bucket=bucket_name, Key=object_key, UploadId=upload_id, PartNumber=part_number, Body=current_part
                    )
                    parts.append({"PartNumber": part_number, "ETag": part["ETag"]})
                    part_number += 1
                    current_part = b""

            # Upload the last part even if it's smaller than MIN_PART_SIZE
            if current_part:
                part = s3_client.upload_part(
                    Bucket=bucket_name, Key=object_key, UploadId=upload_id, PartNumber=part_number, Body=current_part
                )
                parts.append({"PartNumber": part_number, "ETag": part["ETag"]})

            # Complete the multipart upload
            s3_client.complete_multipart_upload(
                Bucket=bucket_name, Key=object_key, UploadId=upload_id, MultipartUpload={"Parts": parts}
            )
        except Exception as e:
            # Abort the multipart upload if something goes wrong
            s3_client.abort_multipart_upload(Bucket=bucket_name, Key=object_key, UploadId=upload_id)
            current_app.logger.error(f"Failed to upload report: {str(e)}")
            raise

    # Generate presigned URL
    url = generate_presigned_url(
        bucket_name=bucket_name,
        object_key=object_key,
        expiration=THREE_DAYS_IN_SECONDS,
    )
    return url
