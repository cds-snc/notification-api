import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock, call

import pytest
import pytz
from botocore.exceptions import ClientError
from flask import current_app
from freezegun import freeze_time
from tests.app.conftest import datetime_in_past

from app.aws.s3 import (
    filter_s3_bucket_objects_within_date_range,
    generate_presigned_url,
    get_list_of_files_by_suffix,
    get_s3_bucket_objects,
    get_s3_file,
    remove_jobs_from_s3,
    remove_transformed_dvla_file,
    stream_to_s3,
    upload_job_to_s3,
    upload_report_to_s3,
)


def single_s3_object_stub(key="foo", last_modified=datetime.utcnow()):
    return {
        "ETag": '"d41d8cd98f00b204e9800998ecf8427e"',
        "Key": key,
        "LastModified": last_modified,
    }


def test_get_s3_file_makes_correct_call(notify_api, mocker):
    get_s3_mock = mocker.patch("app.aws.s3.get_s3_object")
    get_s3_file("foo-bucket", "bar-file.txt")

    get_s3_mock.assert_called_with("foo-bucket", "bar-file.txt")


def test_remove_transformed_dvla_file_makes_correct_call(notify_api, mocker):
    s3_mock = mocker.patch("app.aws.s3.get_s3_object")
    fake_uuid = "5fbf9799-6b9b-4dbb-9a4e-74a939f3bb49"

    remove_transformed_dvla_file(fake_uuid)

    s3_mock.assert_has_calls(
        [
            call(
                current_app.config["DVLA_BUCKETS"]["job"],
                "{}-dvla-job.text".format(fake_uuid),
            ),
            call().delete(),
        ]
    )


def test_get_s3_bucket_objects_make_correct_pagination_call(notify_api, mocker):
    paginator_mock = mocker.patch("app.aws.s3.client")

    get_s3_bucket_objects("foo-bucket", subfolder="bar")

    paginator_mock.assert_has_calls([call().get_paginator().paginate(Bucket="foo-bucket", Prefix="bar")])


def test_get_s3_bucket_objects_builds_objects_list_from_paginator(notify_api, mocker):
    AFTER_SEVEN_DAYS = datetime_in_past(days=8)
    paginator_mock = mocker.patch("app.aws.s3.client")
    multiple_pages_s3_object = [
        {
            "Contents": [
                single_s3_object_stub("bar/foo.txt", AFTER_SEVEN_DAYS),
            ]
        },
        {
            "Contents": [
                single_s3_object_stub("bar/foo1.txt", AFTER_SEVEN_DAYS),
            ]
        },
    ]
    paginator_mock.return_value.get_paginator.return_value.paginate.return_value = multiple_pages_s3_object

    bucket_objects = get_s3_bucket_objects("foo-bucket", subfolder="bar")

    assert len(bucket_objects) == 2
    assert set(bucket_objects[0].keys()) == set(["ETag", "Key", "LastModified"])


@freeze_time("2016-01-01 11:00:00")
def test_get_s3_bucket_objects_removes_redundant_root_object(notify_api, mocker):
    AFTER_SEVEN_DAYS = datetime_in_past(days=8)
    s3_objects_stub = [
        single_s3_object_stub("bar/", AFTER_SEVEN_DAYS),
        single_s3_object_stub("bar/foo.txt", AFTER_SEVEN_DAYS),
    ]

    filtered_items = filter_s3_bucket_objects_within_date_range(s3_objects_stub)

    assert len(filtered_items) == 1

    assert filtered_items[0]["Key"] == "bar/foo.txt"
    assert filtered_items[0]["LastModified"] == datetime_in_past(days=8)


@freeze_time("2016-01-01 11:00:00")
def test_filter_s3_bucket_objects_within_date_range_filters_by_date_range(notify_api, mocker):
    START_DATE = datetime_in_past(days=9)
    JUST_BEFORE_START_DATE = START_DATE - timedelta(seconds=1)
    JUST_AFTER_START_DATE = START_DATE + timedelta(seconds=1)
    END_DATE = datetime_in_past(days=7)
    JUST_BEFORE_END_DATE = END_DATE - timedelta(seconds=1)
    JUST_AFTER_END_DATE = END_DATE + timedelta(seconds=1)

    s3_objects_stub = [
        single_s3_object_stub("bar/", JUST_BEFORE_START_DATE),
        single_s3_object_stub("bar/foo.txt", START_DATE),
        single_s3_object_stub("bar/foo2.txt", JUST_AFTER_START_DATE),
        single_s3_object_stub("bar/foo3.txt", JUST_BEFORE_END_DATE),
        single_s3_object_stub("bar/foo4.txt", END_DATE),
        single_s3_object_stub("bar/foo5.txt", JUST_AFTER_END_DATE),
    ]

    filtered_items = filter_s3_bucket_objects_within_date_range(s3_objects_stub)

    assert len(filtered_items) == 2

    assert filtered_items[0]["Key"] == "bar/foo2.txt"
    assert filtered_items[0]["LastModified"] == JUST_AFTER_START_DATE

    assert filtered_items[1]["Key"] == "bar/foo3.txt"
    assert filtered_items[1]["LastModified"] == JUST_BEFORE_END_DATE


@freeze_time("2016-01-01 11:00:00")
def test_get_s3_bucket_objects_does_not_return_outside_of_date_range(notify_api, mocker):
    START_DATE = datetime_in_past(days=9)
    JUST_BEFORE_START_DATE = START_DATE - timedelta(seconds=1)
    END_DATE = datetime_in_past(days=7)
    JUST_AFTER_END_DATE = END_DATE + timedelta(seconds=1)

    s3_objects_stub = [
        single_s3_object_stub("bar/", JUST_BEFORE_START_DATE),
        single_s3_object_stub("bar/foo1.txt", START_DATE),
        single_s3_object_stub("bar/foo2.txt", END_DATE),
        single_s3_object_stub("bar/foo3.txt", JUST_AFTER_END_DATE),
    ]

    filtered_items = filter_s3_bucket_objects_within_date_range(s3_objects_stub)

    assert len(filtered_items) == 0


@freeze_time("2018-01-11 00:00:00")
@pytest.mark.parametrize(
    "suffix_str, days_before, returned_no",
    [
        (".ACK.txt", None, 1),
        (".ack.txt", None, 1),
        (".ACK.TXT", None, 1),
        ("", None, 2),
        ("", 1, 1),
    ],
)
def test_get_list_of_files_by_suffix(notify_api, mocker, suffix_str, days_before, returned_no):
    paginator_mock = mocker.patch("app.aws.s3.client")
    multiple_pages_s3_object = [
        {
            "Contents": [
                single_s3_object_stub("bar/foo.ACK.txt", datetime_in_past(1, 0)),
            ]
        },
        {
            "Contents": [
                single_s3_object_stub("bar/foo1.rs.txt", datetime_in_past(2, 0)),
            ]
        },
    ]
    paginator_mock.return_value.get_paginator.return_value.paginate.return_value = multiple_pages_s3_object
    if days_before:
        key = get_list_of_files_by_suffix(
            "foo-bucket",
            subfolder="bar",
            suffix=suffix_str,
            last_modified=datetime.now(tz=pytz.utc) - timedelta(days=days_before),
        )
    else:
        key = get_list_of_files_by_suffix("foo-bucket", subfolder="bar", suffix=suffix_str)

    assert sum(1 for x in key) == returned_no
    for k in key:
        assert k == "bar/foo.ACK.txt"


def test_get_list_of_files_by_suffix_empty_contents_return_with_no_error(notify_api, mocker):
    paginator_mock = mocker.patch("app.aws.s3.client")
    multiple_pages_s3_object = [
        {
            "other_content": [
                "some_values",
            ]
        }
    ]
    paginator_mock.return_value.get_paginator.return_value.paginate.return_value = multiple_pages_s3_object
    key = get_list_of_files_by_suffix("foo-bucket", subfolder="bar", suffix=".pdf")

    assert sum(1 for x in key) == 0


def test_upload_job_to_s3(notify_api, mocker):
    utils_mock = mocker.patch("app.aws.s3.utils_s3upload")
    service_id = uuid.uuid4()
    csv_data = "foo"

    upload_id = upload_job_to_s3(service_id, csv_data)

    utils_mock.assert_called_once_with(
        filedata=csv_data,
        region=notify_api.config["AWS_REGION"],
        bucket_name=current_app.config["CSV_UPLOAD_BUCKET_NAME"],
        file_location=f"service-{service_id}-notify/{upload_id}.csv",
    )


def test_remove_jobs_from_s3(notify_api, mocker):
    mock = Mock()
    mocker.patch("app.aws.s3.resource", return_value=mock)
    jobs = [
        type("Job", (object,), {"service_id": "foo", "id": "j1"}),
        type("Job", (object,), {"service_id": "foo", "id": "j2"}),
        type("Job", (object,), {"service_id": "foo", "id": "j3"}),
        type("Job", (object,), {"service_id": "foo", "id": "j4"}),
        type("Job", (object,), {"service_id": "foo", "id": "j5"}),
    ]

    remove_jobs_from_s3(jobs, batch_size=2)

    mock.assert_has_calls(
        [
            call.Bucket(current_app.config["CSV_UPLOAD_BUCKET_NAME"]),
            call.Bucket().delete_objects(
                Delete={"Objects": [{"Key": "service-foo-notify/j1.csv"}, {"Key": "service-foo-notify/j2.csv"}]}
            ),
            call.Bucket().delete_objects(
                Delete={"Objects": [{"Key": "service-foo-notify/j3.csv"}, {"Key": "service-foo-notify/j4.csv"}]}
            ),
            call.Bucket().delete_objects(Delete={"Objects": [{"Key": "service-foo-notify/j5.csv"}]}),
        ]
    )


def test_upload_report_to_s3(notify_api, mocker):
    utils_mock = mocker.patch("app.aws.s3.utils_s3upload")
    presigned_url_mock = mocker.patch("app.aws.s3.generate_presigned_url")
    service_id = uuid.uuid4()
    report_id = uuid.uuid4()
    csv_data = b"foo"
    file_location = f"service-{service_id}/{report_id}.csv"
    upload_report_to_s3(service_id, report_id, csv_data)

    utils_mock.assert_called_once_with(
        filedata=csv_data,
        region=notify_api.config["AWS_REGION"],
        bucket_name=current_app.config["REPORTS_BUCKET_NAME"],
        file_location=file_location,
    )
    presigned_url_mock.assert_called_once_with(
        bucket_name=current_app.config["REPORTS_BUCKET_NAME"],
        object_key=file_location,
        expiration=259200,  # 3 days
    )


def test_generate_presigned_url_success(notify_api, mocker):
    s3_client_mock = mocker.patch("app.aws.s3.client")
    s3_client_mock.return_value.generate_presigned_url.return_value = "https://example.com/presigned-url"

    bucket_name = "test-bucket"
    object_key = "test-object"
    expiration = 3600

    url = generate_presigned_url(bucket_name, object_key, expiration)

    s3_client_mock.assert_called_once_with("s3", notify_api.config["AWS_REGION"])
    s3_client_mock.return_value.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": bucket_name, "Key": object_key},
        ExpiresIn=expiration,
    )
    assert url == "https://example.com/presigned-url"


def test_generate_presigned_url_error(notify_api, mocker):
    s3_client_mock = mocker.patch("app.aws.s3.client")
    s3_client_mock.return_value.generate_presigned_url.side_effect = ClientError(
        error_response={"Error": {"Code": "403", "Message": "Forbidden"}},
        operation_name="GeneratePresignedUrl",
    )

    bucket_name = "test-bucket"
    object_key = "test-object"
    expiration = 3600

    url = generate_presigned_url(bucket_name, object_key, expiration)

    s3_client_mock.assert_called_once_with("s3", notify_api.config["AWS_REGION"])
    s3_client_mock.return_value.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": bucket_name, "Key": object_key},
        ExpiresIn=expiration,
    )
    assert not url


def test_stream_to_s3(notify_api, mocker):
    s3_client_mock = mocker.patch("app.aws.s3.client")
    cursor_mock = Mock()
    buffer_mock = mocker.patch("app.aws.s3.BytesIO", return_value=Mock())
    transfer_config_mock = mocker.patch("app.aws.s3.TransferConfig")

    bucket_name = "test-bucket"
    object_key = "test-object"
    copy_command = "COPY (SELECT * FROM test_table) TO STDOUT WITH CSV"

    stream_to_s3(bucket_name, object_key, copy_command, cursor_mock)

    cursor_mock.copy_expert.assert_called_once_with(copy_command, buffer_mock.return_value)
    buffer_mock.return_value.seek.assert_has_calls([call(0, 2), call(0)])
    s3_client_mock.return_value.upload_fileobj.assert_called_once_with(
        Fileobj=buffer_mock.return_value,
        Bucket=bucket_name,
        Key=object_key,
        Config=transfer_config_mock.return_value,
    )
