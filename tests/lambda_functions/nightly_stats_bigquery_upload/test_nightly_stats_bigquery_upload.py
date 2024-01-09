import csv

import pytest
import json
from io import StringIO

from botocore.response import StreamingBody
from google.auth.credentials import Credentials
from google.cloud.bigquery import Client
from google.cloud.exceptions import NotFound

from lambda_functions.nightly_stats_bigquery_upload.nightly_stats_bigquery_upload_lambda import (
    get_object_key,
    get_bucket_name,
    lambda_handler,
)

# region mocking

# from https://docs.aws.amazon.com/AmazonS3/latest/userguide/notification-content-structure.html
EXAMPLE_S3_EVENT = {
    'Records': [
        {
            'eventVersion': '2.1',
            'eventSource': 'aws:s3',
            'awsRegion': 'us-west-2',
            'eventTime': '1970-01-01T00:00:00.000Z',
            'eventName': 'ObjectCreated:Put',
            'userIdentity': {'principalId': 'AIDAJDPLRKLG7UEXAMPLE'},
            'requestParameters': {'sourceIPAddress': '127.0.0.1'},
            'responseElements': {
                'x-amz-request-id': 'C3D13FE58DE4C810',
                'x-amz-id-2': 'FMyUVURIY8/IgAtTv8xRjskZQpcIZ9KG4V5Wp6S7S/JRWeUWerMUE5JgHvANOjpD',
            },
            's3': {
                's3SchemaVersion': '1.0',
                'configurationId': 'testConfigRule',
                'bucket': {
                    'name': 'my_stats_bucket',
                    'ownerIdentity': {'principalId': 'A3NL1KOZZKExample'},
                    'arn': 'arn:aws:s3:::my_stats_bucket',
                },
                'object': {
                    'key': '2021-06-28.csv',
                    'size': 1024,
                    'eTag': 'd41d8cd98f00b204e9800998ecf8427e',
                    'versionId': '096fKKXTRTtl3on89fVO.nfljtsv6qko',
                    'sequencer': '0055AED6DCD90281E5',
                },
            },
        }
    ]
}

EXAMPLE_SERVICE_ACCOUNT_INFO = {
    'type': 'service_account',
    'private_key': 'foo',
    'client_email': 'some email',
    'token_uri': 'some uri',
}

EXAMPLE_NIGHTLY_STATS_LIST = [
    ['service id', 'service name', 'template id', 'template name', 'status', 'count', 'channel_type'],
    ['some service id', 'some service name', 'some template id', 'some template name', 'some status', '5', 'email'],
    ['other service id', 'other service name', 'other template id', 'other template name', 'other status', '5', 'sms'],
]


@pytest.fixture
def example_nightly_stats_bytes() -> bytes:
    nightly_stats_buffer = StringIO()
    writer = csv.writer(nightly_stats_buffer)
    writer.writerows(EXAMPLE_NIGHTLY_STATS_LIST)
    return nightly_stats_buffer.getvalue().encode()


@pytest.fixture
def mock_s3_client(mocker, example_nightly_stats_bytes):
    mock_client = mocker.Mock()

    mock_object_body = mocker.Mock(StreamingBody, read=mocker.Mock(return_value=example_nightly_stats_bytes))
    mock_client.get_object.return_value = {'Body': mock_object_body, 'ContentType': 'text/csv', 'ContentLength': 100}

    return mock_client


@pytest.fixture
def mock_ssm_client(mocker):
    mock_client = mocker.Mock()
    mock_client.get_parameter.return_value = {'Parameter': {'Value': json.dumps(EXAMPLE_SERVICE_ACCOUNT_INFO)}}
    return mock_client


@pytest.fixture(autouse=True)
def mock_boto(mocker, mock_s3_client, mock_ssm_client):
    mock_boto = mocker.patch(
        'lambda_functions.nightly_stats_bigquery_upload.nightly_stats_bigquery_upload_lambda.boto3'
    )
    mock_boto.client.side_effect = lambda service_name: {'s3': mock_s3_client, 'ssm': mock_ssm_client}[service_name]


@pytest.fixture(autouse=True)
def mock_credentials(mocker):
    mock_service_account = mocker.patch(
        'lambda_functions.nightly_stats_bigquery_upload.nightly_stats_bigquery_upload_lambda.service_account'
    )

    mock_service_account.Credentials.from_service_account_info.return_value = mocker.Mock(Credentials)


@pytest.fixture(autouse=True)
def mock_bigquery_client(mocker):
    mock_bigquery = mocker.patch(
        'lambda_functions.nightly_stats_bigquery_upload.nightly_stats_bigquery_upload_lambda.bigquery'
    )

    mock_client = mocker.Mock(Client)
    mock_bigquery.Client.return_value = mock_client

    return mock_client


# endregion


class TestEventParsing:
    def test_should_get_object_key(self):
        assert get_object_key(EXAMPLE_S3_EVENT) == '2021-06-28.csv'

    def test_should_get_bucket_name(self):
        assert get_bucket_name(EXAMPLE_S3_EVENT) == 'my_stats_bucket'


class TestLambdaHandler:
    @pytest.fixture(autouse=True)
    def some_env(self, monkeypatch):
        monkeypatch.setenv('ENVIRONMENT', 'some-env')

    expected_table_id = 'vsp-analytics-and-insights.platform_vanotify.some-env-statistics'

    def test_should_read_service_account_info_from_ssm(self, monkeypatch, mock_ssm_client):
        lambda_handler(EXAMPLE_S3_EVENT, 'some context')
        mock_ssm_client.get_parameter.assert_called_with(Name='/bigquery/credentials', WithDecryption=True)

    def test_should_read_nightly_stats_from_s3(self, mock_s3_client):
        lambda_handler(EXAMPLE_S3_EVENT, 'some context')
        mock_s3_client.get_object.assert_called_with(Bucket='my_stats_bucket', Key='2021-06-28.csv')

    def test_should_delete_existing_stats_from_bigquery_table_if_table_exists(
        self, monkeypatch, mock_bigquery_client, example_nightly_stats_bytes
    ):
        mock_bigquery_client.get_table.side_effect = None
        lambda_handler(EXAMPLE_S3_EVENT, 'some context')

        assert mock_bigquery_client.query.called_with(
            f"DELETE FROM `{self.expected_table_id}` WHERE date = '2021-06-28'"
        )

    def test_should_not_delete_existing_stats_from_bigquery_table_if_table_does_not_exist(
        self, monkeypatch, mock_bigquery_client, example_nightly_stats_bytes
    ):
        mock_bigquery_client.get_table.side_effect = NotFound('foo')
        lambda_handler(EXAMPLE_S3_EVENT, 'some context')
        mock_bigquery_client.query.assert_not_called()

    def test_should_load_stats_into_bigquery_table(
        self, monkeypatch, mock_bigquery_client, example_nightly_stats_bytes
    ):
        lambda_handler(EXAMPLE_S3_EVENT, 'some context')

        _, kwargs = mock_bigquery_client.load_table_from_file.call_args

        assert kwargs['destination'] == self.expected_table_id
        assert kwargs['file_obj'].getvalue() == example_nightly_stats_bytes
