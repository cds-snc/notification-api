import magic
from flask import current_app

from app.attachments.exceptions import UnsupportedMimeTypeException


def extract_and_validate_mimetype(
    file_data: bytes,
    file_name: str,
) -> str:
    mimetype = magic.from_buffer(file_data, mime=True)

    if mimetype not in current_app.config['ATTACHMENTS_ALLOWED_MIME_TYPES']:
        raise UnsupportedMimeTypeException(
            f"Unsupported attachment type '{mimetype}'. "
            f"Supported types are: {current_app.config['ATTACHMENTS_ALLOWED_MIME_TYPES']}"
        )

    # Our MIME type auto-detection resolves CSV content as text/plain, so we fix that if possible
    if file_name.lower().endswith('.csv') and mimetype == 'text/plain':
        mimetype = 'text/csv'

    return mimetype
