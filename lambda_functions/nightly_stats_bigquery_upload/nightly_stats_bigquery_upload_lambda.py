import os
import urllib
import six
from typing import Dict

import json

import boto3

from google.cloud import bigquery
from google.oauth2 import service_account
from google.cloud.exceptions import NotFound


def read_service_account_info_from_ssm() -> Dict:
    ssm_client = boto3.client('ssm')

    key = '/bigquery/credentials'
    response = ssm_client.get_parameter(Name=key, WithDecryption=True)
    value = response['Parameter']['Value']
    return json.loads(value)


def get_object_key(event):
    return urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'], encoding='utf-8')


def get_bucket_name(event) -> str:
    return event['Records'][0]['s3']['bucket']['name']


def read_nightly_stats_from_s3(
    bucket_name: str,
    object_key: str,
) -> bytes:
    s3_client = boto3.client('s3')

    return s3_client.get_object(Bucket=bucket_name, Key=object_key)['Body'].read()


def delete_existing_rows_for_date(
    bigquery_client: bigquery.Client,
    table_id: str,
    object_key: str,
) -> None:
    date, _extension = object_key.split('.')
    dml_statement = f"DELETE FROM `{table_id}` WHERE date = '{date}'"
    bigquery_client.query(dml_statement).result()


def add_updated_rows_for_date(
    bigquery_client: bigquery.Client,
    table_id: str,
    nightly_stats: bytes,
) -> None:
    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField('date', 'DATE'),
            bigquery.SchemaField('service_id', 'STRING'),
            bigquery.SchemaField('service_name', 'STRING'),
            bigquery.SchemaField('template_id', 'STRING'),
            bigquery.SchemaField('template_name', 'STRING'),
            bigquery.SchemaField('status', 'STRING'),
            bigquery.SchemaField('status_reason', 'STRING'),
            bigquery.SchemaField('count', 'INTEGER'),
            bigquery.SchemaField('channel_type', 'STRING'),
        ],
        skip_leading_rows=1,
    )

    bigquery_client.load_table_from_file(
        file_obj=six.BytesIO(nightly_stats), destination=table_id, job_config=job_config
    ).result()


def lambda_handler(
    event,
    _context,
):
    service_account_info = read_service_account_info_from_ssm()
    credentials = service_account.Credentials.from_service_account_info(service_account_info)

    bigquery_client = bigquery.Client(credentials=credentials)

    table_id = f'vsp-analytics-and-insights.platform_vanotify.{os.getenv("ENVIRONMENT")}-statistics'

    bucket_name = get_bucket_name(event)
    object_key = get_object_key(event)

    try:
        bigquery_client.get_table(table_id)
    except NotFound:
        pass
    else:
        delete_existing_rows_for_date(bigquery_client, table_id, object_key)

    nightly_stats = read_nightly_stats_from_s3(bucket_name, object_key)

    add_updated_rows_for_date(bigquery_client, table_id, nightly_stats)

    return {'statusCode': 200}
