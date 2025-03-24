import json
import logging
import os
import six
import urllib
from typing import Dict

import boto3
from google.cloud import bigquery
from google.oauth2 import service_account
from google.cloud.exceptions import NotFound

ENVIRONMENT = os.getenv('ENVIRONMENT', 'test')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO' if ENVIRONMENT == 'prod' else 'DEBUG')

TABLE_ID_STATS = f'vsp-analytics-and-insights.platform_vanotify.{ENVIRONMENT}-statistics'
TABLE_ID_BILLING = f'vsp-analytics-and-insights.platform_vanotify.{ENVIRONMENT}-billing'

logger = logging.getLogger('NightlyBigQueryLambda')
logger.setLevel(LOG_LEVEL)


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
    date: str,
) -> None:
    dml_statement = f'DELETE FROM `{table_id}` WHERE date = @date'  # nosec
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('date', 'STRING', date),
        ]
    )

    bigquery_client.query_and_wait(dml_statement, job_config=job_config)


def _get_schema(table_id: str) -> list[bigquery.SchemaField]:
    schema = []
    if table_id == TABLE_ID_STATS:
        schema = [
            bigquery.SchemaField('date', 'DATE'),
            bigquery.SchemaField('service_id', 'STRING'),
            bigquery.SchemaField('service_name', 'STRING'),
            bigquery.SchemaField('template_id', 'STRING'),
            bigquery.SchemaField('template_name', 'STRING'),
            bigquery.SchemaField('status', 'STRING'),
            bigquery.SchemaField('status_reason', 'STRING'),
            bigquery.SchemaField('count', 'INTEGER'),
            bigquery.SchemaField('channel_type', 'STRING'),
        ]
    elif table_id == TABLE_ID_BILLING:
        schema = [
            bigquery.SchemaField('date', 'DATE'),
            bigquery.SchemaField('service_name', 'STRING'),
            bigquery.SchemaField('service_id', 'STRING'),
            bigquery.SchemaField('template_name', 'STRING'),
            bigquery.SchemaField('template_id', 'STRING'),
            bigquery.SchemaField('sender', 'STRING'),
            bigquery.SchemaField('sender_id', 'STRING'),
            bigquery.SchemaField('billing_code', 'STRING'),
            bigquery.SchemaField('count', 'INTEGER'),
            bigquery.SchemaField('channel_type', 'STRING'),
            bigquery.SchemaField('total_message_parts', 'INTEGER'),
            bigquery.SchemaField('total_cost', 'FLOAT'),
        ]
    else:
        raise ValueError(f'Unexpected table_id: {table_id}')

    return schema


def add_updated_rows_for_date(
    bigquery_client: bigquery.Client,
    table_id: str,
    nightly_stats: bytes,
) -> None:
    job_config = bigquery.LoadJobConfig(
        schema=_get_schema(table_id),
        skip_leading_rows=1,
    )

    bigquery_client.load_table_from_file(
        file_obj=six.BytesIO(nightly_stats), destination=table_id, job_config=job_config
    ).result()


def lambda_handler(
    event,
    _context,
) -> dict[str, int]:
    logger.debug('get credentials . . .')
    service_account_info = read_service_account_info_from_ssm()
    credentials = service_account.Credentials.from_service_account_info(service_account_info)
    logger.debug('. . . credentials obtained')

    logger.debug('creating bigquery client . . .')
    bigquery_client = bigquery.Client(credentials=credentials)
    logger.debug('. . . bigquery client created')

    logger.debug('getting bucket name and object key . . .')
    bucket_name = get_bucket_name(event)
    object_key = get_object_key(event)
    logger.debug('. . . bucket name and object key obtained')

    # get the date and data_type (billing or stats) from the s3 object key
    date, data_type, _ext = object_key.split('.')

    # determine the table id based on the data_type
    if data_type == 'stats':
        table_id = TABLE_ID_STATS
    elif data_type == 'billing':
        table_id = TABLE_ID_BILLING
    else:
        raise ValueError(f'Unexpected data type, expected "stats" or "billing" got: "{data_type}"')

    logger.debug('checking if table exists . . .')
    try:
        bigquery_client.get_table(table_id)
    except NotFound:
        # logging table_id is sensitive information, so we log the data_type instead
        logger.exception('%s table not found', data_type)
        raise
    logger.debug('. . . table exists')

    logger.debug('deleting existing rows for data_type %s for date %s . . .', data_type, date)
    delete_existing_rows_for_date(bigquery_client, table_id, date)
    logger.debug('. . . deleted existing rows data_type %s for date %s', data_type, date)

    logger.debug('reading nightly stats from s3 for %s and date %s . . .', data_type, date)
    nightly_stats = read_nightly_stats_from_s3(bucket_name, object_key)
    logger.debug('. . . nightly stats read from s3 for %s and date %s', data_type, date)

    logger.debug('adding updated %s rows for date %s . . .', data_type, date)
    add_updated_rows_for_date(bigquery_client, table_id, nightly_stats)
    logger.debug('. . . updated rows for %s and date %s', data_type, date)

    return {'statusCode': 200}
