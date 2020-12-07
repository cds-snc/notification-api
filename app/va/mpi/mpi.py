import requests
from app.va import IdentifierType
from app.va.mpi import (
    UnsupportedIdentifierException,
    IdentifierNotFound,
    MpiException
)


class MpiClient:
    SYSTEM_IDENTIFIER = "200ENTF"

    FHIR_FORMAT_SUFFIXES = {
        IdentifierType.ICN: "^NI^200M^USVHA",
        IdentifierType.PID: "^PI^200CORP^USVBA",
        IdentifierType.VA_PROFILE_ID: "^PI^200VETS^USDVA"
    }

    def init_app(self, logger, url, ssl_cert_path, ssl_key_path):
        self.logger = logger
        self.base_url = url
        self.ssl_cert_path = ssl_cert_path
        self.ssl_key_path = ssl_key_path

    def transform_to_fhir_format(self, recipient_identifier):
        try:
            identifier_type = IdentifierType(recipient_identifier.id_type)
            return f"{recipient_identifier.id_value}{self.FHIR_FORMAT_SUFFIXES[identifier_type]}"
        except ValueError as e:
            self.logger.exception(e)
            raise UnsupportedIdentifierException(f"No identifier of type: {recipient_identifier.id_type}") from e
        except KeyError as e:
            self.logger.exception(e)
            raise UnsupportedIdentifierException(f"No mapping for identifier: {identifier_type}") from e

    def get_va_profile_id(self, notification):
        identifiers = notification.recipient_identifiers.values()
        if len(identifiers) != 1:
            error_message = "Unexpected number of recipient_identifiers in: " \
                            f"{notification.recipient_identifiers.keys()}"
            self.logger.warning(error_message)
            raise ValueError(error_message)
        fhir_identifier = self.transform_to_fhir_format(next(iter(identifiers)))
        params = {'-sender': self.SYSTEM_IDENTIFIER}

        try:
            response = requests.get(
                f"{self.base_url}/psim_webservice/fhir/Patient/{fhir_identifier}",
                params=params,
                cert=(self.ssl_cert_path, self.ssl_key_path)
            )
            identifiers = self._get_json_response(response)['identifier']
            active_va_profile_suffix = self.FHIR_FORMAT_SUFFIXES[IdentifierType.VA_PROFILE_ID] + '^A'

            va_profile_id = next(
                identifier['value'].split('^')[0] for identifier in identifiers
                if identifier['value'].endswith(active_va_profile_suffix)
            )
            return va_profile_id

        except requests.HTTPError as e:
            self.logger.exception(e)
            raise MpiException(f"MPI returned {str(e)} while querying for VA Profile ID") from e
        except StopIteration as e:
            self.logger.exception(e)
            raise IdentifierNotFound(f"No active VA Profile Identifier found for: {fhir_identifier}") from e

    def _get_json_response(self, response):
        response.raise_for_status()
        json_response = response.json()
        if json_response.get('severity'):
            error_message = \
                f"MPI returned error with severity: {json_response['severity']}, " \
                f"code: {json_response['details']['coding'][0]['code']}, " \
                f"description: {json_response['details']['text']}"
            self.logger.warning(error_message)
            raise MpiException(error_message)
        return json_response
