import os
import urllib
import io
import csv
import six
from typing import Dict

import json

import boto3

from google.cloud import bigquery
from google.oauth2 import service_account


def read_service_account_info_from_ssm() -> Dict:
    ssm_client = boto3.client('ssm')

    key = f"/bigquery/credentials"
    response = ssm_client.get_parameter(
        Name=key,
        WithDecryption=True
    )
    value = response["Parameter"]["Value"]
    return json.loads(value)


def get_object_key(event):
    return urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'], encoding='utf-8')


def get_bucket_name(event) -> str:
    return event['Records'][0]['s3']['bucket']['name']


def read_nightly_stats_from_s3(bucket_name: str, object_key: str) -> bytes:
    s3_client = boto3.client('s3')

    return s3_client.get_object(Bucket=bucket_name, Key=object_key)['Body'].read()


def lambda_handler(event, _context):

    service_account_info = read_service_account_info_from_ssm()
    credentials = service_account.Credentials.from_service_account_info(service_account_info)

    bigquery_client = bigquery.Client(credentials=credentials)

    table_id = f'vsp-analytics-and-insights.platform_vanotify.{os.getenv("ENVIRONMENT")}-statistics'

    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField("date", "DATE"),
            bigquery.SchemaField("service id", "STRING") ,
            bigquery.SchemaField("service name", "STRING"),
            bigquery.SchemaField("template id", "STRING"),
            bigquery.SchemaField("template name", "STRING"),
            bigquery.SchemaField("status", "STRING"),
            bigquery.SchemaField("status reason", "STRING"),
            bigquery.SchemaField("count", "INTEGER")
        ],
        skip_leading_rows=1
    )

    bucket_name = get_bucket_name(event)
    object_key = get_object_key(event)

    nightly_stats = read_nightly_stats_from_s3(bucket_name, object_key)

    bigquery_client.load_table_from_file(
        file_obj=six.BytesIO(nightly_stats),
        destination=table_id,
        job_config=job_config
    ).result()

    return {
        'statusCode': 200
    }
