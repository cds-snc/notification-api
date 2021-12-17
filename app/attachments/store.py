import os
import uuid
import base64
import boto3
from botocore.exceptions import ClientError as BotoClientError
from notifications_utils.clients.statsd.statsd_client import StatsdClient

from app.attachments.types import SendingMethod, PutReturn


class AttachmentStoreError(Exception):
    pass


class AttachmentStore:
    def __init__(self, bucket=None):
        self.bucket = bucket
        self.s3 = None
        self.logger = None
        self.statsd_client = None

    def init_app(self, endpoint_url: str, bucket: str, logger, statsd_client: StatsdClient):
        self.s3 = boto3.client("s3", endpoint_url=endpoint_url)
        self.bucket = bucket
        self.logger = logger
        self.statsd_client = statsd_client

    def put(
            self,
            service_id: uuid.UUID,
            attachment_stream,
            sending_method: SendingMethod,
            mimetype: str
    ) -> PutReturn:

        encryption_key = self.generate_encryption_key()
        attachment_id = uuid.uuid4()

        attachment_key = self.get_attachment_key(service_id, attachment_id, sending_method)

        self.logger.info(f"putting attachment object in s3 with key {attachment_key} and mimetype {mimetype}")

        try:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=attachment_key,
                Body=attachment_stream,
                ContentType=mimetype,
                SSECustomerKey=encryption_key,
                SSECustomerAlgorithm='AES256'
            )
        except BotoClientError as e:
            self.logger.error(f"error putting attachment object in s3: {e.response['Error']}")
            self.statsd_client.incr('attachments.put.error')
            raise AttachmentStoreError() from e
        else:
            self.statsd_client.incr('attachments.put.success')
            return PutReturn(
                attachment_id=attachment_id,
                encryption_key=base64.b64encode(encryption_key).decode('utf-8')
            )

    def get(
            self,
            service_id: uuid.UUID,
            attachment_id: uuid.UUID,
            decryption_key: str,
            sending_method: SendingMethod
    ) -> bytes:
        attachment_key = self.get_attachment_key(service_id, attachment_id, sending_method)
        self.logger.info(f"getting attachment object from s3 with key {attachment_key}")
        try:
            attachment = self.s3.get_object(
                Bucket=self.bucket,
                Key=attachment_key,
                SSECustomerKey=base64.b64decode(decryption_key),
                SSECustomerAlgorithm='AES256'
            )
        except BotoClientError as e:
            self.logger.error(
                f"error getting attachment object from 3 with key {attachment_key}: {e.response['Error']}"
            )
            self.statsd_client.incr('attachments.get.error')
            raise AttachmentStoreError() from e
        else:
            self.statsd_client.incr('attachments.get.success')
            return attachment['Body'].read().decode('utf-8')

    @staticmethod
    def generate_encryption_key() -> bytes:
        return os.urandom(32)

    @staticmethod
    def get_attachment_key(
            service_id: uuid.UUID,
            attachment_id: uuid.UUID,
            sending_method: SendingMethod = None
    ) -> str:
        key_prefix = 'tmp/' if sending_method == 'attach' else ''
        return f"{key_prefix}{service_id}/{attachment_id}"
