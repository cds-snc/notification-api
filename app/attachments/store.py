import os
import uuid
from typing_extensions import TypedDict

import boto3
from botocore.exceptions import ClientError as BotoClientError
from botocore.response import StreamingBody

from app.attachments.types import SendingMethod


class AttachmentStoreError(Exception):
    pass


class AttachmentStore:
    def __init__(self, bucket=None):
        self.s3 = boto3.client("s3")
        self.bucket = bucket

    def init_app(self, app):
        self.bucket = app.config['ATTACHMENTS_BUCKET']

    def put(
            self,
            service_id: uuid.UUID,
            attachment_stream,
            sending_method: SendingMethod,
            mimetype: str
    ) -> TypedDict('PutReturn', {'id': uuid.UUID, 'encryption_key': bytes}):

        encryption_key = self.generate_encryption_key()
        attachment_id = uuid.uuid4()

        self.s3.put_object(
            Bucket=self.bucket,
            Key=self.get_attachment_key(service_id, attachment_id, sending_method),
            Body=attachment_stream,
            ContentType=mimetype,
            SSECustomerKey=encryption_key,
            SSECustomerAlgorithm='AES256'
        )

        return {
            'id': attachment_id,
            'encryption_key': encryption_key
        }

    def get(
            self,
            service_id: uuid.UUID,
            attachment_id: uuid.UUID,
            decryption_key: bytes,
            sending_method: SendingMethod
    ) -> TypedDict('GetReturn', {'body': StreamingBody, 'mimetype': str, 'size': int}):
        try:
            attachment = self.s3.get_object(
                Bucket=self.bucket,
                Key=self.get_attachment_key(service_id, attachment_id, sending_method),
                SSECustomerKey=decryption_key,
                SSECustomerAlgorithm='AES256'
            )

        except BotoClientError as e:
            raise AttachmentStoreError(e.response['Error'])

        return {
            'body': attachment['Body'],
            'mimetype': attachment['ContentType'],
            'size': attachment['ContentLength']
        }

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
