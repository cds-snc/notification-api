import requests
from time import monotonic
from app.va.identifier import IdentifierType, transform_to_fhir_format, is_fhir_format, FHIR_FORMAT_SUFFIXES
from app.va.mpi import (
    MpiNonRetryableException,
    MpiRetryableException,
    IdentifierNotFound,
    IncorrectNumberOfIdentifiersException,
    MultipleActiveVaProfileIdsException,
    BeneficiaryDeceasedException
)


class MpiClient:
    SYSTEM_IDENTIFIER = "200ENTF"

    def init_app(self, logger, url, ssl_cert_path, ssl_key_path, statsd_client):
        self.logger = logger
        self.base_url = url
        self.ssl_cert_path = ssl_cert_path
        self.ssl_key_path = ssl_key_path
        self.statsd_client = statsd_client

    def get_va_profile_id(self, notification):
        recipient_identifiers = notification.recipient_identifiers.values()
        if len(recipient_identifiers) != 1:
            error_message = "Unexpected number of recipient_identifiers in: " \
                            f"{notification.recipient_identifiers.keys()}"
            self.statsd_client.incr("clients.mpi.incorrect_number_of_recipient_identifiers_error")
            raise IncorrectNumberOfIdentifiersException(error_message)

        recipient_identifier = next(iter(recipient_identifiers))

        if is_fhir_format(recipient_identifier.id_value):
            fhir_identifier = recipient_identifier.id_value
        else:
            fhir_identifier = transform_to_fhir_format(recipient_identifier)

        response_json = self._make_request(fhir_identifier, notification.id)
        mpi_identifiers = response_json['identifier']

        va_profile_id = self._get_active_va_profile_id(mpi_identifiers, fhir_identifier)
        self.statsd_client.incr("clients.mpi.success")
        return va_profile_id

    def _make_request(self, fhir_identifier, notification_id):
        self.logger.info(f"Querying MPI with {fhir_identifier} for notification {notification_id}")
        start_time = monotonic()
        try:
            response = requests.get(
                f"{self.base_url}/psim_webservice/fhir/Patient/{fhir_identifier}",
                params={'-sender': self.SYSTEM_IDENTIFIER},
                cert=(self.ssl_cert_path, self.ssl_key_path)
            )
            response.raise_for_status()
        except requests.HTTPError as e:
            self.statsd_client.incr(f"clients.mpi.error.{e.response.status_code}")
            message = f"MPI returned {str(e)} while querying for notification {notification_id}"
            if e.response.status_code in [429, 500, 502, 503, 504]:
                raise MpiRetryableException(message) from e
            else:
                raise MpiNonRetryableException(message) from e
        except requests.RequestException as e:
            self.statsd_client.incr(f"clients.mpi.error.request_exception")
            message = f"MPI returned {str(e)} while querying for notification {notification_id}"
            raise MpiRetryableException(message) from e
        else:
            self._validate_response(response.json(), notification_id, fhir_identifier)
            self._assert_not_deceased(response.json(), fhir_identifier)
            return response.json()
        finally:
            elapsed_time = monotonic() - start_time
            self.statsd_client.timing("clients.mpi.request-time", elapsed_time)

    def _get_active_va_profile_id(self, identifiers, fhir_identifier):
        active_va_profile_suffix = FHIR_FORMAT_SUFFIXES[IdentifierType.VA_PROFILE_ID] + '^A'
        va_profile_ids = [identifier['value'].split('^')[0] for identifier in identifiers
                          if identifier['value'].endswith(active_va_profile_suffix)]
        if not va_profile_ids:
            self.statsd_client.incr("clients.mpi.error.no_va_profile_id")
            raise IdentifierNotFound(f"No active VA Profile Identifier found for: {fhir_identifier}")
        if len(va_profile_ids) > 1:
            self.statsd_client.incr("clients.mpi.error.multiple_va_profile_ids")
            raise MultipleActiveVaProfileIdsException(
                f"Multiple active VA Profile Identifiers found for: {fhir_identifier}"
            )
        return va_profile_ids[0]

    def _validate_response(self, response_json, notification_id, fhir_identifier):
        if response_json.get('severity'):
            error_message = \
                f"MPI returned error with severity: {response_json['severity']}, " \
                f"code: {response_json['details']['coding'][0]['code']}, " \
                f"description: {response_json['details']['text']} for notification {notification_id} with" \
                f"fhir {fhir_identifier}"
            self.statsd_client.incr("clients.mpi.error")
            raise MpiNonRetryableException(error_message)

    def _assert_not_deceased(self, response_json, fhir_identifier):
        if response_json.get('deceasedDateTime'):
            self.statsd_client.incr("clients.mpi.beneficiary_deceased")
            raise BeneficiaryDeceasedException(
                f"Beneficiary deceased for identifier: {fhir_identifier}"
            )
