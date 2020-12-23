from enum import Enum


class IdentifierType(Enum):

    VA_PROFILE_ID = 'VAPROFILEID'
    PID = 'PID'
    ICN = 'ICN'
    BIRLSID = 'BIRLSID'

    @staticmethod
    def values():
        return list(x.value for x in IdentifierType)


def is_fhir_format(identifier_value: str) -> bool:
    return identifier_value.count('^') >= 1
