import ssl
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.ssl_ import create_urllib3_context
from time import monotonic
from uuid import UUID
from http.client import responses
from functools import reduce

from app.constants import HTTP_TIMEOUT
from app.va.identifier import (
    IdentifierType,
    transform_to_fhir_format,
    is_fhir_format,
    FHIR_FORMAT_SUFFIXES,
    transform_from_fhir_format,
)
from app.va.mpi import (
    MpiNonRetryableException,
    MpiRetryableException,
    IdentifierNotFound,
    NoSuchIdentifierException,
    IncorrectNumberOfIdentifiersException,
    MultipleActiveVaProfileIdsException,
    BeneficiaryDeceasedException,
)

exception_code_mapping = {
    'GCID01': NoSuchIdentifierException,
    '557': NoSuchIdentifierException,
    'BR001': NoSuchIdentifierException,
    'BRNOARG01': MpiNonRetryableException,
    '556': MpiNonRetryableException,
}

exception_substring = {NoSuchIdentifierException: 'no_such_identifier'}

ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

ciphers = [c['name'] for c in ctx.get_ciphers()]
# this is the expected cipher to connect to MPI (services.eauth.va.gov:9303)
ciphers.append('AES256-GCM-SHA384')

# This is the openssl cipher string, containing relevant ciphers.
MPI_CIPHERS = ':'.join(ciphers)


# create a custom HTTPAdapter to connect to MPI using an expanded cipher list
class MPIAdapter(HTTPAdapter):
    """
    A TransportAdapter that uses an expanded cipher list in Requests.
    """

    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context(ciphers=MPI_CIPHERS)
        kwargs['ssl_context'] = context
        return super(MPIAdapter, self).init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        context = create_urllib3_context(ciphers=MPI_CIPHERS)
        kwargs['ssl_context'] = context
        return super(MPIAdapter, self).proxy_manager_for(*args, **kwargs)


def _get_nested_value_from_response_body(
    response_body,
    keys,
    default=None,
):
    return reduce(
        lambda d, key: d.get(key, default) if isinstance(d, dict) else None if not d else d[0],
        keys.split('.'),
        response_body,
    )


class MpiClient:
    SYSTEM_IDENTIFIER = '200ENTF'

    def init_app(
        self,
        logger,
        url,
        ssl_cert_path,
        ssl_key_path,
        statsd_client,
    ):
        self.timeout = HTTP_TIMEOUT
        self.logger = logger
        self.base_url = url
        self.ssl_cert_path = ssl_cert_path
        self.ssl_key_path = ssl_key_path
        self.statsd_client = statsd_client
        self.mpi_adapter = MPIAdapter()

    def get_va_profile_id(
        self,
        notification,
    ):
        recipient_identifiers = notification.recipient_identifiers.values()
        if len(recipient_identifiers) != 1:
            error_message = (
                f'Unexpected number of recipient_identifiers in: {notification.recipient_identifiers.keys()}'
            )
            self.statsd_client.incr('clients.mpi.get_va_profile_id.error.incorrect_number_of_recipient_identifiers')
            raise IncorrectNumberOfIdentifiersException(error_message)

        recipient_identifier = next(iter(recipient_identifiers))

        if is_fhir_format(recipient_identifier.id_value):
            fhir_identifier = recipient_identifier.id_value
        else:
            fhir_identifier = transform_to_fhir_format(recipient_identifier)

        response_json = self._make_request(fhir_identifier, notification.id, recipient_identifier.id_type)

        # Protect PII that can be logged when errors happen
        fhir_identifier = '<redacted>' if recipient_identifier.id_type == IdentifierType.ICN.value else fhir_identifier
        self._assert_not_deceased(response_json, fhir_identifier)
        mpi_identifiers = response_json['identifier']

        va_profile_id = self._get_active_va_profile_id(mpi_identifiers, fhir_identifier)
        self.statsd_client.incr('clients.mpi.get_va_profile_id.success')
        return va_profile_id

    def _make_request(
        self,
        fhir_identifier: str,
        notification_id: UUID,
        id_type: str,
    ):
        self.logger.debug('Querying MPI with %s for notification %s', fhir_identifier, notification_id)
        start_time = monotonic()
        try:
            # Need to make the request with an expanded list of ciphers to make sure we can connect to MPI in Prod
            with requests.session() as s:
                s.mount(self.base_url, adapter=self.mpi_adapter)

                response = s.get(
                    f'{self.base_url}/psim_webservice/fhir/Patient/{fhir_identifier}',
                    params={'-sender': self.SYSTEM_IDENTIFIER},
                    cert=(self.ssl_cert_path, self.ssl_key_path),
                    timeout=self.timeout,
                )

                response.raise_for_status()
        except requests.HTTPError as e:
            self.statsd_client.incr(f'clients.mpi.error.{e.response.status_code}')
            message = f'MPI returned {str(e)} while querying for notification {notification_id}'

            failure_reason = (
                f'Received {responses[e.response.status_code]} HTTP error ({e.response.status_code}) while '
                'making a request to obtain info from MPI'
            )

            if e.response.status_code in [429, 500, 502, 503, 504]:
                self.logger.warning(message)
                exception = MpiRetryableException(message)
                exception.failure_reason = failure_reason
                raise exception from e
            else:
                self.logger.exception(message)
                exception = MpiNonRetryableException(message)
                exception.failure_reason = failure_reason
                raise exception from e
        except requests.RequestException as e:
            self.statsd_client.incr('clients.mpi.error.request_exception')
            message = f'MPI returned RequestException while querying for FHIR identifier: {str(e)}'
            exception = MpiRetryableException(message)
            exception.failure_reason = exception
            raise exception from e
        else:
            self._validate_response(
                response.json(),
                notification_id,
                '<redacted>' if id_type == IdentifierType.ICN.value else fhir_identifier,
            )
            self.statsd_client.incr('clients.mpi.success')
            return response.json()
        finally:
            elapsed_time = monotonic() - start_time
            self.statsd_client.timing('clients.mpi.request-time', elapsed_time)

    def _get_active_va_profile_id(
        self,
        identifiers,
        fhir_identifier,
    ):
        active_va_profile_suffix = FHIR_FORMAT_SUFFIXES[IdentifierType.VA_PROFILE_ID] + '^A'
        va_profile_ids = [
            transform_from_fhir_format(identifier['value'])
            for identifier in identifiers
            if identifier['value'].endswith(active_va_profile_suffix)
        ]
        if not va_profile_ids:
            self.statsd_client.incr('clients.mpi.get_va_profile_id.error.no_va_profile_id')
            raise IdentifierNotFound(f'No active VA Profile Identifier found for: {fhir_identifier}')
        if len(va_profile_ids) > 1:
            self.statsd_client.incr('clients.mpi.get_va_profile_id.error.multiple_va_profile_ids')
            raise MultipleActiveVaProfileIdsException(
                f'Multiple active VA Profile Identifiers found for: {fhir_identifier}'
            )
        return va_profile_ids[0]

    def _validate_response(
        self,
        response_json,
        notification_id,
        fhir_identifier,
    ):
        if response_json.get('severity'):
            error_code = _get_nested_value_from_response_body(response_json, 'details.coding.index.code')
            error_message = (
                f'MPI returned error: {response_json} for notification {notification_id} with fhir {fhir_identifier}'
            )
            if exception_code_mapping.get(error_code):
                exception = exception_code_mapping.get(error_code)
                exception_text = exception_substring.get(exception)
                self.statsd_client.incr(
                    'clients.mpi.get_va_profile_id.error.' + exception_text if exception_text else 'clients.mpi.error'
                )
                raise exception(error_message)
            else:
                self.statsd_client.incr('clients.mpi.error')
                raise MpiNonRetryableException(error_message)

    def _assert_not_deceased(
        self,
        response_json,
        fhir_identifier,
    ):
        if response_json.get('deceasedDateTime'):
            self.statsd_client.incr('clients.mpi.get_va_profile_id.beneficiary_deceased')
            raise BeneficiaryDeceasedException(f'Beneficiary deceased for identifier: {fhir_identifier}')
