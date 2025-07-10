from typing import ClassVar

from app.pii.pii_base import Pii, PiiLevel
from app.va.identifier import IdentifierType


class PiiPid(Pii):
    _level: ClassVar[PiiLevel] = PiiLevel.LOW

    def get_identifier_type(self) -> IdentifierType:
        return IdentifierType.PID


class PiiVaProfileID(Pii):
    _level: ClassVar[PiiLevel] = PiiLevel.LOW

    def get_identifier_type(self) -> IdentifierType:
        return IdentifierType.VA_PROFILE_ID
