import copy
import csv
import json
from io import StringIO
from unittest import mock

import boto3
import pytest
from google.api_core.exceptions import TooManyRequests
from google.auth.credentials import Credentials
from google.cloud.bigquery import Client
from google.cloud.exceptions import NotFound
from moto import mock_aws

import lambda_functions.nightly_stats_bigquery_upload.nightly_stats_bigquery_upload_lambda as nightly_lambda

AWS_REGION = 'us-gov-west-1'
BUCKET_NAME = 'my_stats_bucket'
BQ_TABLE_ID = 'test_table_id'
OBJECT_KEY_STATS = '2021-06-28.stats.csv'
OBJECT_KEY_BILLING = '2021-06-28.billing.csv'

# from https://docs.aws.amazon.com/AmazonS3/latest/userguide/notification-content-structure.html
EXAMPLE_S3_EVENT_STATS = {
    'Records': [
        {
            'eventVersion': '2.2',
            'eventSource': 'aws:s3',
            'awsRegion': AWS_REGION,
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
                    'name': BUCKET_NAME,
                    'ownerIdentity': {'principalId': 'A3NL1KOZZKExample'},
                    'arn': f'arn:aws:s3:::{BUCKET_NAME}',
                },
                'object': {
                    'key': OBJECT_KEY_STATS,
                    'size': 1024,
                    'eTag': 'd41d8cd98f00b204e9800998ecf8427e',
                    'versionId': '096fKKXTRTtl3on89fVO.nfljtsv6qko',
                    'sequencer': '0055AED6DCD90281E5',
                },
            },
        }
    ]
}

EXAMPLE_S3_EVENT_BILLING = copy.deepcopy(EXAMPLE_S3_EVENT_STATS)
EXAMPLE_S3_EVENT_BILLING['Records'][0]['s3']['object']['key'] = OBJECT_KEY_BILLING

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

EXAMPLE_NIGHTLY_BILLING_LIST = [
    [
        'service_name',
        'service_id',
        'template_name',
        'template_id',
        'sender',
        'sender_id',
        'billing_code',
        'count',
        'channel_type',
        'total_message_parts',
        'total_cost',
    ],
    [
        'some service name',
        'some service id',
        'some template name',
        'some template id',
        'some sender',
        'some sender id',
        'some billing code',
        '4',
        'sms',
        '9',
        '753.1',
    ],
    [
        'other service name',
        'other service id',
        'other template name',
        'other template id',
        'other sender',
        'other sender id',
        'other billing code',
        '5',
        'sms',
        '5',
        '555.4',
    ],
]


def example_bytes(example_list: list[list[str]]) -> bytes:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerows(example_list)
    return buffer.getvalue().encode()


@pytest.fixture(scope='module')
def mock_s3_client():
    with mock_aws():
        s3_client = boto3.client('s3', region_name=AWS_REGION)
        s3_client.create_bucket(
            Bucket=BUCKET_NAME,
            CreateBucketConfiguration={'LocationConstraint': AWS_REGION},
        )

        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=OBJECT_KEY_STATS,
            Body=example_bytes(EXAMPLE_NIGHTLY_STATS_LIST),
        )

        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=OBJECT_KEY_BILLING,
            Body=example_bytes(EXAMPLE_NIGHTLY_STATS_LIST),
        )

        yield s3_client

        s3_client.delete_object(Bucket=BUCKET_NAME, Key=OBJECT_KEY_BILLING)
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=OBJECT_KEY_STATS)
        s3_client.delete_bucket(Bucket=BUCKET_NAME)


@pytest.fixture(scope='module')
def mock_ssm_client():
    with mock_aws():
        ssm_client = boto3.client('ssm', region_name=AWS_REGION)
        ssm_client.put_parameter(
            Name='/bigquery/credentials',
            Value=json.dumps(EXAMPLE_SERVICE_ACCOUNT_INFO),
            Type='SecureString',
        )

        yield ssm_client

        ssm_client.delete_parameter(Name='/bigquery/credentials')


@pytest.fixture
def mock_bigquery_client(mocker):
    mock_bigquery = mocker.patch(
        'lambda_functions.nightly_stats_bigquery_upload.nightly_stats_bigquery_upload_lambda.bigquery'
    )

    mock_client = mocker.Mock(Client)
    mock_bigquery.Client.return_value = mock_client

    return mock_client


@pytest.fixture(autouse=True)
def mock_credentials(mocker):
    mock_service_account = mocker.patch(
        'lambda_functions.nightly_stats_bigquery_upload.nightly_stats_bigquery_upload_lambda.service_account'
    )

    mock_service_account.Credentials.from_service_account_info.return_value = mocker.Mock(Credentials)


@pytest.fixture
def mock_logger(mocker):
    return mocker.patch('lambda_functions.nightly_stats_bigquery_upload.nightly_stats_bigquery_upload_lambda.logger')


class TestParameterAccess:
    @staticmethod
    def test_read_service_account_info_from_ssm(mock_ssm_client) -> None:
        assert nightly_lambda.read_service_account_info_from_ssm() == EXAMPLE_SERVICE_ACCOUNT_INFO


class TestEventParsing:
    @staticmethod
    @pytest.mark.parametrize(
        'example_event, expected_object_key',
        [
            (EXAMPLE_S3_EVENT_STATS, OBJECT_KEY_STATS),
            (EXAMPLE_S3_EVENT_BILLING, OBJECT_KEY_BILLING),
        ],
        ids=['stats', 'billing'],
    )
    def test_get_object_key(example_event, expected_object_key) -> None:
        assert nightly_lambda.get_object_key(example_event) == expected_object_key

    @staticmethod
    def test_get_bucket_name() -> None:
        assert nightly_lambda.get_bucket_name(EXAMPLE_S3_EVENT_STATS) == BUCKET_NAME


class TestS3Access:
    @staticmethod
    @pytest.mark.parametrize(
        'object_key, expected_response',
        [
            (OBJECT_KEY_STATS, example_bytes(EXAMPLE_NIGHTLY_STATS_LIST)),
            (OBJECT_KEY_BILLING, example_bytes(EXAMPLE_NIGHTLY_STATS_LIST)),
        ],
        ids=['stats', 'billing'],
    )
    def test_read_nightly_stats_from_s3(mock_s3_client, object_key, expected_response) -> None:
        response = nightly_lambda.read_nightly_stats_from_s3(BUCKET_NAME, object_key)
        assert response == expected_response


class TestBigQueryAccess:
    @staticmethod
    def test_delete_existing_rows_for_date(mock_bigquery_client) -> None:
        date, _type, _ext = OBJECT_KEY_STATS.split('.')

        nightly_lambda.delete_existing_rows_for_date(mock_bigquery_client, BQ_TABLE_ID, date)

        mock_bigquery_client.query_and_wait.assert_called_once_with(
            f'DELETE FROM `{BQ_TABLE_ID}` WHERE date = @date',
            job_config=mock.ANY,
        )

    @staticmethod
    def test_delete_existing_rows_for_date_raises_error_if_exception(mock_bigquery_client, mock_logger) -> None:
        mock_bigquery_client.query_and_wait.side_effect = TooManyRequests('test')

        with pytest.raises(TooManyRequests):
            nightly_lambda.delete_existing_rows_for_date(mock_bigquery_client, BQ_TABLE_ID, '2021-06-28')

        mock_logger.exception.assert_called_once()

    @staticmethod
    @pytest.mark.parametrize(
        'bq_table_id, example_nightly_bytes',
        [
            (nightly_lambda.TABLE_ID_STATS, example_bytes(EXAMPLE_NIGHTLY_STATS_LIST)),
            (nightly_lambda.TABLE_ID_BILLING, example_bytes(EXAMPLE_NIGHTLY_STATS_LIST)),
        ],
        ids=['stats', 'billing'],
    )
    def test_add_updated_rows_for_date(mock_bigquery_client, bq_table_id, example_nightly_bytes) -> None:
        nightly_lambda.add_updated_rows_for_date(mock_bigquery_client, bq_table_id, example_nightly_bytes)

        _, kwargs = mock_bigquery_client.load_table_from_file.call_args

        assert kwargs['destination'] == bq_table_id
        assert kwargs['file_obj'].getvalue() == example_nightly_bytes

    @staticmethod
    def test_add_updated_rows_for_date_raises_exception(mock_bigquery_client, mock_logger) -> None:
        mock_bigquery_client.load_table_from_file.side_effect = TooManyRequests('test')

        with pytest.raises(TooManyRequests):
            nightly_lambda.add_updated_rows_for_date(mock_bigquery_client, nightly_lambda.TABLE_ID_STATS, b'foo')

        mock_logger.exception.assert_called_once()

    @staticmethod
    def test_get_schema() -> None:
        schema = nightly_lambda._get_schema(nightly_lambda.TABLE_ID_STATS)

        # there are 9 columns in the stats table
        assert len(schema) == 9

        # check the first and last column names and types
        assert schema[0].name == 'date'
        assert schema[0].field_type == 'DATE'
        assert schema[-1].name == 'channel_type'
        assert schema[-1].field_type == 'STRING'

    @staticmethod
    def test_get_schema_raises_error_with_incorrect_table() -> None:
        with pytest.raises(ValueError):
            nightly_lambda._get_schema('unexpected_table_id')


class TestLambdaHandler:
    @staticmethod
    @pytest.mark.parametrize(
        'example_event, expected_table_id',
        [
            (EXAMPLE_S3_EVENT_STATS, nightly_lambda.TABLE_ID_STATS),
            (EXAMPLE_S3_EVENT_BILLING, nightly_lambda.TABLE_ID_BILLING),
        ],
        ids=['stats', 'billing'],
    )
    def test_lambda_handler(
        mock_ssm_client,
        mock_s3_client,
        mock_bigquery_client,
        example_event,
        expected_table_id,
    ) -> None:
        response = nightly_lambda.lambda_handler(example_event, 'some context')

        assert mock_bigquery_client.get_table.called_with(expected_table_id)
        assert mock_bigquery_client.query_and_wait.called
        assert mock_bigquery_client.load_table_from_file.called

        assert response == {'statusCode': 200}

    @staticmethod
    def test_should_not_delete_existing_stats_from_bigquery_table_if_table_does_not_exist(
        mock_ssm_client,
        mock_bigquery_client,
    ) -> None:
        mock_bigquery_client.get_table.side_effect = NotFound('foo')

        with pytest.raises(NotFound):
            nightly_lambda.lambda_handler(EXAMPLE_S3_EVENT_STATS, 'some context')

        mock_bigquery_client.query_and_wait.assert_not_called()

    @staticmethod
    def test_handler_raises_error_if_data_type_is_not_found(mock_ssm_client, mock_bigquery_client) -> None:
        example_s3_event_invalid = copy.deepcopy(EXAMPLE_S3_EVENT_STATS)
        example_s3_event_invalid['Records'][0]['s3']['object']['key'] = '2021-06-28.invalid.csv'

        with pytest.raises(ValueError):
            nightly_lambda.lambda_handler(example_s3_event_invalid, 'some context')
