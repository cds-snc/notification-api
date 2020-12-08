import requests
from app.va import IdentifierType
from app.va.mpi import (
    UnsupportedIdentifierException,
    IdentifierNotFound,
    MpiException,
    IncorrectNumberOfIdentifiersException
)


class MpiClient:
    SYSTEM_IDENTIFIER = "200ENTF"

    FHIR_FORMAT_SUFFIXES = {
        IdentifierType.ICN: "^NI^200M^USVHA",
        IdentifierType.PID: "^PI^200CORP^USVBA",
        IdentifierType.VA_PROFILE_ID: "^PI^200VETS^USDVA",
        IdentifierType.BIRLSID: "^PI^200BRLS^USDVA"
    }

    def init_app(self, logger, url, ssl_cert_path, ssl_key_path, statsd_client):
        self.logger = logger
        self.base_url = url
        self.ssl_cert_path = ssl_cert_path
        self.ssl_key_path = ssl_key_path
        self.statsd_client = statsd_client

    def transform_to_fhir_format(self, recipient_identifier):
        try:
            identifier_type = IdentifierType(recipient_identifier.id_type)
            return f"{recipient_identifier.id_value}{self.FHIR_FORMAT_SUFFIXES[identifier_type]}", \
                   identifier_type, \
                   recipient_identifier.id_value
        except ValueError as e:
            self.logger.exception(e)
            raise UnsupportedIdentifierException(f"No identifier of type: {recipient_identifier.id_type}") from e
        except KeyError as e:
            self.logger.exception(e)
            raise UnsupportedIdentifierException(f"No mapping for identifier: {identifier_type}") from e

    def get_va_profile_id(self, notification):
        recipient_identifiers = notification.recipient_identifiers.values()
        if len(recipient_identifiers) != 1:
            error_message = "Unexpected number of recipient_identifiers in: " \
                            f"{notification.recipient_identifiers.keys()}"
            self.logger.warning(error_message)
            self.statsd_client.incr("clients.mpi.incorrect_number_of_recipient_identifiers_error")
            raise IncorrectNumberOfIdentifiersException(error_message)

        fhir_identifier, id_type, id_value = self.transform_to_fhir_format(next(iter(recipient_identifiers)))

        self.logger.info(f"Querying MPI with {id_type} {id_value}")
        response_json = self._make_request(fhir_identifier, notification.id)
        mpi_identifiers = response_json['identifier']

        va_profile_id = self.get_profile_id(mpi_identifiers, fhir_identifier)
        self.statsd_client.incr("clients.mpi.get_va_profile_id.success")
        return va_profile_id

    def _make_request(self, fhir_identifier, notification_id):
        try:
            response = requests.get(
                f"{self.base_url}/psim_webservice/fhir/Patient/{fhir_identifier}",
                params={'-sender': self.SYSTEM_IDENTIFIER},
                cert=(self.ssl_cert_path, self.ssl_key_path)
            )
            response.raise_for_status()
            self._validate_response(response.json(), notification_id, fhir_identifier)
            return response.json()
        except requests.HTTPError as e:
            self.logger.exception(e)
            self.statsd_client.incr(f"clients.mpi.error.{e.response.status_code}")
            raise MpiException(f"MPI returned {str(e)} while querying for notification {notification_id}") from e

    def get_profile_id(self, identifiers, fhir_identifier):
        active_va_profile_suffix = self.FHIR_FORMAT_SUFFIXES[IdentifierType.VA_PROFILE_ID] + '^A'
        try:
            va_profile_id = next(
                identifier['value'].split('^')[0] for identifier in identifiers
                if identifier['value'].endswith(active_va_profile_suffix)
            )
            return va_profile_id
        except StopIteration as e:
            self.logger.exception(e)
            self.statsd_client.incr("clients.mpi.get_va_profile_id.error")
            raise IdentifierNotFound(f"No active VA Profile Identifier found for: {fhir_identifier}") from e

    def _validate_response(self, response_json, notification_id, fhir_identifier):
        if response_json.get('severity'):
            error_message = \
                f"MPI returned error with severity: {response_json['severity']}, " \
                f"code: {response_json['details']['coding'][0]['code']}, " \
                f"description: {response_json['details']['text']} for notification {notification_id} with" \
                f"fhir {fhir_identifier}"
            self.logger.warning(error_message)
            self.statsd_client.incr("clients.mpi.error")
            raise MpiException(error_message)

        self.statsd_client.incr("clients.mpi.success")
