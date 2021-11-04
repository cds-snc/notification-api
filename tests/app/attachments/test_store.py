import uuid
from unittest import mock

import pytest
from botocore.exceptions import ClientError as BotoClientError

from tests.conftest import set_config, Matcher

from app.attachments.store import AttachmentStore, AttachmentStoreError


@pytest.fixture
def store(mocker, notify_api):
    mock_boto = mocker.patch('app.attachments.store.boto3')
    mock_boto.client.return_value.get_object.return_value = {
        'Body': mock.Mock(),
        'ContentType': 'application/pdf',
        'ContentLength': 100
    }
    store = AttachmentStore()
    with set_config(notify_api, 'ATTACHMENTS_BUCKET', 'test-bucket'):
        store.init_app(notify_api)
    return store


def test_attachment_key_with_uuid(store):
    service_id = uuid.uuid4()
    attachment_id = uuid.uuid4()

    assert store.get_attachment_key(service_id, attachment_id) == "{}/{}".format(str(service_id), str(attachment_id))


def test_put_attachment(store):
    service_id = uuid.uuid4()
    ret = store.put(service_id, mock.Mock(), sending_method='link', mimetype='application/pdf')

    assert ret == {
        'id': Matcher('UUID length match', lambda x: len(str(x)) == 36),
        'encryption_key': Matcher('32 bytes', lambda x: len(x) == 32 and isinstance(x, bytes))
    }

    store.s3.put_object.assert_called_once_with(
        Body=mock.ANY,
        Bucket='test-bucket',
        ContentType='application/pdf',
        Key=Matcher(
            'attachment key',
            lambda attachment_key:
                attachment_key.startswith(f"{service_id}/") and len(attachment_key.split('/')[-1]) == 36
        ),
        SSECustomerKey=ret['encryption_key'],
        SSECustomerAlgorithm='AES256'
    )


def test_put_attachment_attach_tmp_dir(store):
    service_id = uuid.uuid4()
    ret = store.put(service_id, mock.Mock(), sending_method='attach', mimetype='application/pdf')

    assert ret == {
        'id': Matcher('UUID length match', lambda x: len(str(x)) == 36),
        'encryption_key': Matcher('32 bytes', lambda x: len(x) == 32 and isinstance(x, bytes))
    }

    store.s3.put_object.assert_called_once_with(
        Body=mock.ANY,
        Bucket='test-bucket',
        ContentType='application/pdf',
        Key=Matcher(
            'attachment key',
            lambda attachment_key:
                attachment_key.startswith(f"tmp/{service_id}/") and len(attachment_key.split('/')[-1]) == 36
        ),
        SSECustomerKey=ret['encryption_key'],
        SSECustomerAlgorithm='AES256'
    )


def test_get_attachment(store):
    service_id = uuid.uuid4()
    attachment_id = uuid.uuid4()

    assert store.get(service_id, attachment_id, bytes(32), sending_method='link') == {
        'body': mock.ANY,
        'mimetype': 'application/pdf',
        'size': 100,
    }

    store.s3.get_object.assert_called_once_with(
        Bucket='test-bucket',
        Key=f"{service_id}/{attachment_id}",
        SSECustomerAlgorithm='AES256',
        # 32 null bytes
        SSECustomerKey=bytes(32),
    )


def test_get_attachment_attach_tmp_dir(store):
    service_id = uuid.uuid4()
    attachment_id = uuid.uuid4()

    assert store.get(service_id, attachment_id, bytes(32), sending_method='attach') == {
        'body': mock.ANY,
        'mimetype': 'application/pdf',
        'size': 100,
    }

    store.s3.get_object.assert_called_once_with(
        Bucket='test-bucket',
        Key=f"tmp/{service_id}/{attachment_id}",
        SSECustomerAlgorithm='AES256',
        # 32 null bytes
        SSECustomerKey=bytes(32),
    )


def test_get_attachment_with_boto_error(store):
    store.s3.get_object = mock.Mock(side_effect=BotoClientError({
        'Error': {
            'Code': 'Error code',
            'Message': 'Error message'
        }
    }, 'GetObject'))

    with pytest.raises(AttachmentStoreError):
        store.get(uuid.uuid4(), uuid.uuid4(), b'0f0f0f', sending_method='link')
