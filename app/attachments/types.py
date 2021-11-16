import uuid
from typing import NamedTuple
from typing_extensions import Literal, TypedDict

SendingMethod = Literal['attach', 'link']


class PutReturn(NamedTuple):
    attachment_id: uuid.UUID
    encryption_key: str


class UploadedAttachmentMetadata(TypedDict):
    id: uuid.UUID
    encryption_key: str
    file_name: str
    sending_method: SendingMethod
