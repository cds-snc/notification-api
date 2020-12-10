from enum import Enum


class IdentifierType(Enum):

    VA_PROFILE_ID = 'VAPROFILEID'
    PID = 'PID'
    ICN = 'ICN'
    BIRLSID = 'BIRLSID'

    @staticmethod
    def values():
        return list(x.value for x in IdentifierType)
