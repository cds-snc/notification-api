import pathlib
import uuid

import magic
from flask import current_app

from app import attachment_store
from app.attachments.exceptions import UnsupportedMimeTypeException
from app.attachments.types import SendingMethod


def upload_attachment(service_id: uuid.UUID, sending_method: SendingMethod, file_data: bytes, file_name: str):

    mimetype = magic.from_buffer(file_data, mime=True)
    if mimetype not in current_app.config['ATTACHMENTS_ALLOWED_MIME_TYPES']:
        raise UnsupportedMimeTypeException(
            f"Unsupported attachment type '{mimetype}'. "
            f"Supported types are: {current_app.config['ATTACHMENTS_ALLOWED_MIME_TYPES']}"
        )

    file_extension = None
    if '.' in file_name:
        file_extension = ''.join(pathlib.Path(file_name.lower()).suffixes).lstrip('.')

    # Our MIME type auto-detection resolves CSV content as text/plain,
    # so we fix that if possible
    if file_name.lower().endswith('.csv') and mimetype == 'text/plain':
        mimetype = 'text/csv'

    attachment = attachment_store.put(service_id, file_data, sending_method=sending_method, mimetype=mimetype)

    return {
        'id': str(attachment['id']),
        'encryption_key': str(attachment['encryption_key']),
        'sending_method': sending_method,
        'mime_type': mimetype,
        'file_name': file_name,
        'file_size': len(file_data),
        'file_extension': file_extension,
    }
