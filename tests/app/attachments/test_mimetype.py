import pytest

from app.attachments.exceptions import UnsupportedMimeTypeException
from app.attachments.mimetype import extract_and_validate_mimetype
from tests.conftest import set_config


@pytest.mark.parametrize(
    'file_data, file_name, expected_mime',
    [
        (b'%PDF-1.4 file contents', 'file.pdf', 'application/pdf'),
        (b'Canada', 'text.txt', 'text/plain'),
        (b'Canada', 'noextension', 'text/plain'),
        (b'foo,bar', 'file.csv', 'text/csv'),
        (b'foo,bar', 'FILE.CSV', 'text/csv'),
    ],
)
def test_returns_expected_mimetype(
    notify_api,
    file_data,
    file_name,
    expected_mime,
):
    with set_config(notify_api, 'ATTACHMENTS_ALLOWED_MIME_TYPES', ['application/pdf', 'text/plain', 'text/csv']):
        mimetype = extract_and_validate_mimetype(file_data=file_data, file_name=file_name)

    assert mimetype == expected_mime


def test_raises_unknown_type(notify_api):
    allowed_types = ['application/pdf', 'text/plain', 'text/csv']

    with set_config(notify_api, 'ATTACHMENTS_ALLOWED_MIME_TYPES', allowed_types):
        with pytest.raises(expected_exception=UnsupportedMimeTypeException) as exc:
            extract_and_validate_mimetype(file_data=b'\x00pdf file contents\n', file_name='file.pdf')

        assert (
            str(exc.value) == "Unsupported attachment type 'application/octet-stream'. "
            f'Supported types are: {allowed_types}'
        )
