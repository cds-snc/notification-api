import uuid

import pytest

from app.attachments.exceptions import UnsupportedMimeTypeException
from app.attachments.types import SendingMethod
from app.attachments.upload import upload_attachment
from tests.conftest import set_config


@pytest.fixture
def store(mocker):
    return mocker.patch('app.attachments.upload.attachment_store')


@pytest.mark.parametrize(
    "file_name, sending_method, expected_file_extension",
    [
        ('custom_file_name.pdf', 'attach', 'pdf'),
        ('whatever', 'link', None)
    ]
)
def test_document_upload_returns_link_to_frontend(
        notify_api,
        store,
        file_name,
        sending_method: SendingMethod,
        expected_file_extension: str,
):
    service_id = uuid.uuid4()
    encryption_key = bytes(32)
    store.put.return_value = {
        'id': 'ffffffff-ffff-ffff-ffff-ffffffffffff',
        'encryption_key': encryption_key,
    }

    with(set_config(notify_api, 'ATTACHMENTS_ALLOWED_MIME_TYPES', ['application/pdf'])):
        response = upload_attachment(service_id, sending_method, b'%PDF-1.4 file contents', file_name)

    assert response == {
        'encryption_key': str(encryption_key),
        'id': 'ffffffff-ffff-ffff-ffff-ffffffffffff',
        'sending_method': sending_method,
        'mime_type': 'application/pdf',
        'file_name': file_name,
        'file_size': 22,
        'file_extension': expected_file_extension
    }


@pytest.mark.parametrize(
    "content, filename, expected_extension, expected_mime, expected_size", [
        (b'%PDF-1.4 file contents', 'file.pdf', 'pdf', 'application/pdf', 22),
        (b'Canada', 'text.txt', 'txt', 'text/plain', 6),
        (b'Canada', 'noextension', None, 'text/plain', 6),
        (b'foo,bar', 'file.csv', 'csv', 'text/csv', 7),
        (b'foo,bar', 'FILE.CSV', 'csv', 'text/csv', 7),
    ]
)
def test_document_upload_returns_size_and_mime(
        notify_api,
        store,
        content,
        filename,
        expected_extension,
        expected_mime,
        expected_size
):
    store.put.return_value = {
        'id': 'ffffffff-ffff-ffff-ffff-ffffffffffff',
        'encryption_key': bytes(32),
    }
    with(set_config(
            notify_api,
            'ATTACHMENTS_ALLOWED_MIME_TYPES',
            ['application/pdf', 'text/plain', 'text/csv']
    )):
        response = upload_attachment(uuid.uuid4(), 'link', content, filename)

    assert response['mime_type'] == expected_mime
    assert response['file_size'] == expected_size
    assert response['file_extension'] == expected_extension


def test_document_upload_unknown_type(notify_api):

    allowed_types = ['application/pdf', 'text/plain', 'text/csv']

    with(set_config(
            notify_api,
            'ATTACHMENTS_ALLOWED_MIME_TYPES',
            allowed_types
    )):
        with pytest.raises(expected_exception=UnsupportedMimeTypeException) as exc:
            upload_attachment(uuid.uuid4(), 'link', b'\x00pdf file contents\n', 'file.pdf')
            print("foo")

        assert str(exc.value) == "Unsupported attachment type 'application/octet-stream'. " \
                                 f"Supported types are: {allowed_types}"
