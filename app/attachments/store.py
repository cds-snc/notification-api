import os
import uuid
import base64
import boto3
from botocore.exceptions import ClientError as BotoClientError

from app.attachments.types import SendingMethod, PutReturn


class AttachmentStoreError(Exception):
    pass


class AttachmentStore:
    def __init__(self, bucket=None):
        self.bucket = bucket
        self.s3 = None
        self.logger = None

    def init_app(self, endpoint_url: str, bucket: str, logger):
        self.s3 = boto3.client("s3", endpoint_url=endpoint_url)
        self.bucket = bucket
        self.logger = logger

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
            raise AttachmentStoreError() from e

        return PutReturn(attachment_id=attachment_id, encryption_key=base64.b64encode(encryption_key).decode('utf-8'))

    def get(
            self,
            service_id: uuid.UUID,
            attachment_id: uuid.UUID,
            decryption_key: str,
            sending_method: SendingMethod
    ) -> bytes:
        try:
            attachment_key = self.get_attachment_key(service_id, attachment_id, sending_method)
            self.logger.info(f"getting attachment object from s3 with key {attachment_key}")
            attachment = self.s3.get_object(
                Bucket=self.bucket,
                Key=attachment_key,
                SSECustomerKey=base64.b64decode(decryption_key),
                SSECustomerAlgorithm='AES256'
            )

        except BotoClientError as e:
            self.logger.error(f"error getting attachment object from s3: {e.response['Error']}")
            raise AttachmentStoreError() from e

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
