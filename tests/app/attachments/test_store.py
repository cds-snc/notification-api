import os
import uuid
import base64
from unittest import mock

import pytest
from botocore.exceptions import ClientError as BotoClientError
from botocore.response import StreamingBody

from tests.conftest import Matcher

from app.attachments.store import AttachmentStore, AttachmentStoreError


@pytest.fixture
def encryption_key():
    return os.urandom(32)


@pytest.fixture
def stringified_encryption_key(encryption_key):
    return base64.b64encode(encryption_key).decode('utf-8')


@pytest.fixture
def store(mocker):
    mock_boto = mocker.patch('app.attachments.store.boto3')
    mock_object_body = mock.Mock(StreamingBody)
    mock_boto.client.return_value.get_object.return_value = {
        'Body': mock_object_body,
        'ContentType': 'application/pdf',
        'ContentLength': 100,
    }
    store = AttachmentStore()
    store.init_app(endpoint_url='some-url', bucket='test-bucket', logger=mocker.Mock(), statsd_client=mocker.Mock())
    return store


def test_attachment_key_with_uuid(store):
    service_id = uuid.uuid4()
    attachment_id = uuid.uuid4()

    assert store.get_attachment_key(service_id, attachment_id) == '{}/{}'.format(str(service_id), str(attachment_id))


def test_put_attachment(store):
    service_id = uuid.uuid4()
    ret = store.put(service_id, mock.Mock(), sending_method='link', mimetype='application/pdf')

    assert len(str(ret.attachment_id)) == 36

    store.s3.put_object.assert_called_once_with(
        Body=mock.ANY,
        Bucket='test-bucket',
        ContentType='application/pdf',
        Key=Matcher(
            'attachment key',
            lambda attachment_key: attachment_key.startswith(f'{service_id}/')
            and len(attachment_key.split('/')[-1]) == 36,
        ),
        SSECustomerKey=base64.b64decode(ret.encryption_key),
        SSECustomerAlgorithm='AES256',
    )


def test_put_attachment_attach_tmp_dir(store):
    service_id = uuid.uuid4()
    ret = store.put(service_id, mock.Mock(), sending_method='attach', mimetype='application/pdf')

    assert len(str(ret.attachment_id)) == 36

    store.s3.put_object.assert_called_once_with(
        Body=mock.ANY,
        Bucket='test-bucket',
        ContentType='application/pdf',
        Key=Matcher(
            'attachment key',
            lambda attachment_key: attachment_key.startswith(f'tmp/{service_id}/')
            and len(attachment_key.split('/')[-1]) == 36,
        ),
        SSECustomerKey=base64.b64decode(ret.encryption_key),
        SSECustomerAlgorithm='AES256',
    )


def test_put_attachment_with_boto_error(store, stringified_encryption_key):
    store.s3.put_object = mock.Mock(
        side_effect=BotoClientError({'Error': {'Code': 'Error code', 'Message': 'Error message'}}, 'PutObject')
    )

    with pytest.raises(AttachmentStoreError):
        store.put(uuid.uuid4(), mock.Mock(), sending_method='attach', mimetype='application/pdf')


def test_get_attachment(store, encryption_key, stringified_encryption_key):
    service_id = uuid.uuid4()
    attachment_id = uuid.uuid4()

    assert store.get(service_id, attachment_id, stringified_encryption_key, sending_method='link') == mock.ANY

    store.s3.get_object.assert_called_once_with(
        Bucket='test-bucket',
        Key=f'{service_id}/{attachment_id}',
        SSECustomerAlgorithm='AES256',
        # 32 null bytes
        SSECustomerKey=encryption_key,
    )


def test_get_attachment_attach_tmp_dir(store, encryption_key, stringified_encryption_key):
    service_id = uuid.uuid4()
    attachment_id = uuid.uuid4()

    assert store.get(service_id, attachment_id, stringified_encryption_key, sending_method='attach') == mock.ANY

    store.s3.get_object.assert_called_once_with(
        Bucket='test-bucket',
        Key=f'tmp/{service_id}/{attachment_id}',
        SSECustomerAlgorithm='AES256',
        # 32 null bytes
        SSECustomerKey=encryption_key,
    )


def test_get_attachment_with_boto_error(store, stringified_encryption_key):
    store.s3.get_object = mock.Mock(
        side_effect=BotoClientError({'Error': {'Code': 'Error code', 'Message': 'Error message'}}, 'GetObject')
    )

    with pytest.raises(AttachmentStoreError):
        store.get(uuid.uuid4(), uuid.uuid4(), stringified_encryption_key, sending_method='link')
