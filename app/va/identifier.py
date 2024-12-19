from enum import Enum

from app.constants import STATUS_REASON_NO_PROFILE


class IdentifierType(Enum):
    VA_PROFILE_ID = 'VAPROFILEID'
    PID = 'PID'
    ICN = 'ICN'
    BIRLSID = 'BIRLSID'
    EDIPI = 'EDIPI'

    @staticmethod
    def values():
        return list(x.value for x in IdentifierType)


def is_fhir_format(identifier_value: str) -> bool:
    return identifier_value.count('^') >= 1


FHIR_FORMAT_SUFFIXES = {
    IdentifierType.ICN: '^NI^200M^USVHA',
    IdentifierType.PID: '^PI^200CORP^USVBA',
    IdentifierType.VA_PROFILE_ID: '^PI^200VETS^USDVA',
    IdentifierType.BIRLSID: '^PI^200BRLS^USVBA',
    IdentifierType.EDIPI: '^NI^200DOD^USDOD',
}

OIDS = {
    IdentifierType.ICN: '2.16.840.1.113883.4.349',
    IdentifierType.PID: '2.16.840.1.113883.4.349',
    IdentifierType.VA_PROFILE_ID: '2.16.840.1.113883.4.349',
    IdentifierType.BIRLSID: '2.16.840.1.113883.4.349',
    IdentifierType.EDIPI: '2.16.840.1.113883.3.42.10001.100001.12',
}


class UnsupportedIdentifierException(Exception):
    failure_reason = 'Unsupported identifier'
    status_reason = STATUS_REASON_NO_PROFILE


def transform_to_fhir_format(recipient_identifier):
    try:
        identifier_type = IdentifierType(recipient_identifier.id_type)
        return f'{recipient_identifier.id_value}{FHIR_FORMAT_SUFFIXES[identifier_type]}'
    except ValueError as e:
        raise UnsupportedIdentifierException(f'No identifier of type: {recipient_identifier.id_type}') from e
    except KeyError as e:
        raise UnsupportedIdentifierException(f'No mapping for identifier: {identifier_type}') from e


def transform_from_fhir_format(fhir_format_identifier: str) -> str:
    return fhir_format_identifier.split('^')[0]
