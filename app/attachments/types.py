import uuid
from typing import NamedTuple

from typing_extensions import Literal

SendingMethod = Literal['attach', 'link']


class PutReturn(NamedTuple):
    attachment_id: uuid.UUID
    encryption_key: str
