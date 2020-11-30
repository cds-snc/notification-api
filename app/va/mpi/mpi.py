import requests
from app.va import IdentifierType


class UnsupportedIdentifierException(Exception):
    pass


class MpiClient:

    SYSTEM_IDENTIFIER = "200ENTF"

    FHIR_FORMAT_SUFFIXES = {
        IdentifierType.ICN: "^NI^200M^USVHA",
        IdentifierType.PID: "^PI^200CORP^USVBA",
        IdentifierType.VA_PROFILE_ID: "^PI^200VETS^USDVA"
    }

    def init_app(self, url):
        self.base_url = url

    def transform_to_fhir_format(self, recipient_identifier):
        try:
            identifier_type = IdentifierType(recipient_identifier.id_type)
            return f"{recipient_identifier.id_value}{self.FHIR_FORMAT_SUFFIXES[identifier_type]}"
        except ValueError as e:
            raise UnsupportedIdentifierException(f"No identifier of type: {recipient_identifier.id_type}") from e
        except KeyError as e:
            raise UnsupportedIdentifierException(f"No mapping for identifier: {identifier_type}") from e

    def get_va_profile_id(self, notification):
        identifiers = notification.recipient_identifiers.values()
        if len(identifiers) != 1:
            raise ValueError(
                f"Unexpected number of recipient_identifiers in: {notification.recipient_identifiers.keys()}")
        fhir_identifier = self.transform_to_fhir_format(next(iter(identifiers)))
        params = {'-sender': self.SYSTEM_IDENTIFIER}
        response = requests.get(f"{self.base_url}/psim_webservice/fhir/Patient/{fhir_identifier}", params=params)
        response.raise_for_status()
        return response.json()['vaprofileId']
