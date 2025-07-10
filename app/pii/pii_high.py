from typing import ClassVar

from app.pii.pii_base import Pii, PiiLevel
from app.va.identifier import IdentifierType


class PiiBirlsid(Pii):
    _level: ClassVar[PiiLevel] = PiiLevel.HIGH

    def get_identifier_type(self) -> IdentifierType:
        return IdentifierType.BIRLSID


class PiiEdipi(Pii):
    _level: ClassVar[PiiLevel] = PiiLevel.HIGH

    def get_identifier_type(self) -> IdentifierType:
        return IdentifierType.EDIPI


class PiiIcn(Pii):
    _level: ClassVar[PiiLevel] = PiiLevel.HIGH

    def get_identifier_type(self) -> IdentifierType:
        return IdentifierType.ICN
