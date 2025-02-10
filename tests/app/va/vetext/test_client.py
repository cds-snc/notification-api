from base64 import b64encode
from unittest import mock
from uuid import uuid4

import pytest
from requests import HTTPError, Response
from requests.exceptions import ConnectTimeout, ReadTimeout, RequestException
from requests_mock import ANY

from app.celery.exceptions import NonRetryableException, RetryableException
from app.mobile_app import DEFAULT_MOBILE_APP_TYPE
from app.va.identifier import IdentifierType
from app.va.vetext import VETextClient
from app.v2.dataclasses import V2PushPayload

from tests.app.factories.recipient_idenfier import sample_recipient_identifier
from tests.app.factories.mobile_app import sample_mobile_app_type


MOCK_VETEXT_URL = 'http://mock.vetext.va.gov'
MOCK_USER = 'some-user'
MOCK_PASSWORD = 'some-password'


@pytest.fixture(scope='function')
def test_vetext_client(mocker):
    test_vetext_client = VETextClient()
    mock_logger = mocker.Mock()
    mock_statsd = mocker.Mock()
    test_vetext_client.init_app(
        MOCK_VETEXT_URL, {'username': MOCK_USER, 'password': MOCK_PASSWORD}, logger=mock_logger, statsd=mock_statsd
    )
    return test_vetext_client


class TestRequestExceptions:
    def test_raises_retryable_error_on_request_exception(self, rmock, test_vetext_client):
        rmock.post(url=f'{MOCK_VETEXT_URL}/mobile/push/send', exc=ConnectTimeout)

        with pytest.raises(RetryableException):
            test_vetext_client.send_push_notification(
                {
                    'appSid': 1111,
                    'templateSid': 2222,
                    'icn': 3333,
                }
            )

    def test_logs_exception_on_read_timeout(self, rmock, test_vetext_client):
        rmock.post(url=f'{MOCK_VETEXT_URL}/mobile/push/send', exc=ReadTimeout)

        test_vetext_client.send_push_notification(
            {
                'appSid': 1111,
                'templateSid': 2222,
                'icn': 3333,
            }
        )
        assert test_vetext_client.logger.exception.called_once

    def test_increments_statsd_and_timing_on_request_exception(self, rmock, test_vetext_client):
        rmock.post(url=f'{MOCK_VETEXT_URL}/mobile/push/send', exc=ConnectTimeout)

        with pytest.raises(RetryableException):
            test_vetext_client.send_push_notification(
                {
                    'appSid': 1111,
                    'templateSid': 2222,
                    'icn': 3333,
                }
            )
        test_vetext_client.statsd.incr.assert_called_with('clients.vetext.error.connection_timeout')
        test_vetext_client.statsd.timing.assert_called_with('clients.vetext.request_time', mock.ANY)


class TestHTTPExceptions:
    @pytest.mark.parametrize('http_status_code', [429, 500, 502, 503, 504])
    def test_raises_on_retryable_http_exception_and_logs(self, rmock, test_vetext_client, http_status_code):
        rmock.post(url=f'{MOCK_VETEXT_URL}/mobile/push/send', status_code=http_status_code)

        payload = {
            'appSid': 1111,
            'templateSid': 2222,
            'icn': 3333,
        }
        with pytest.raises(RetryableException):
            test_vetext_client.send_push_notification(payload)
        assert test_vetext_client.logger.warning.called

    @pytest.mark.parametrize('http_status_code', [401, 404])
    def test_raises_nonretryable_on_request_exception_and_logs(self, rmock, test_vetext_client, http_status_code):
        rmock.post(url=f'{MOCK_VETEXT_URL}/mobile/push/send', status_code=http_status_code)

        with pytest.raises(NonRetryableException):
            test_vetext_client.send_push_notification(
                {
                    'appSid': 1111,
                    'templateSid': 2222,
                    'icn': 3333,
                }
            )
        assert test_vetext_client.logger.exception.called
        test_vetext_client.statsd.incr.assert_called_with(f'clients.vetext.error.{http_status_code}')
        test_vetext_client.statsd.timing.assert_called_with('clients.vetext.request_time', mock.ANY)

    @pytest.mark.parametrize('http_status_code', [429, 500, 502, 503, 504])
    def test_increments_statsd_and_timing_on_http_exception(self, rmock, test_vetext_client, http_status_code):
        rmock.post(url=f'{MOCK_VETEXT_URL}/mobile/push/send', status_code=http_status_code)

        with pytest.raises(RetryableException):
            test_vetext_client.send_push_notification(
                {
                    'appSid': 1111,
                    'templateSid': 2222,
                    'icn': 3333,
                }
            )
        test_vetext_client.statsd.incr.assert_called_with(f'clients.vetext.error.{http_status_code}')
        test_vetext_client.statsd.timing.assert_called_with('clients.vetext.request_time', mock.ANY)

    @pytest.mark.parametrize(
        'response',
        [
            {'idType': 'appSid', 'id': 'foo', 'success': False, 'statusCode': 400, 'error': 'Invalid Application SID'},
            {
                'idType': 'templateSid',
                'id': 'bar',
                'success': False,
                'statusCode': 400,
                'error': 'Invalid Template SID',
            },
            {'success': False, 'statusCode': 400, 'error': 'Template Not Specifified'},
        ],
    )
    def test_raises_bad_request_exception_with_info_on_400_error(self, rmock, test_vetext_client, response):
        rmock.post(url=f'{MOCK_VETEXT_URL}/mobile/push/send', status_code=400, json=response)

        with pytest.raises(NonRetryableException):
            test_vetext_client.send_push_notification(
                {
                    'appSid': 1111,
                    'templateSid': 2222,
                    'icn': 3333,
                }
            )

    def test_raises_bad_request_exception_when_400_error_not_json(self, rmock, test_vetext_client):
        response = 'Unrecognized field &quot;foo&quot; (class gov.va.med.lom.vetext.model.dto.PushNotification),'
        ' not marked as ignorable'
        rmock.post(url=f'{MOCK_VETEXT_URL}/mobile/push/send', status_code=400, text=response)

        with pytest.raises(NonRetryableException):
            test_vetext_client.send_push_notification(
                {
                    'appSid': 1111,
                    'templateSid': 2222,
                    'icn': 3333,
                }
            )


class TestFormatVetextPayload:
    def test_format_happy_path_push(self):
        payload = V2PushPayload(
            DEFAULT_MOBILE_APP_TYPE,
            'any_template_id',
            personalisation={'foo_1': 'bar', 'baz_two': 'abc', 'tmp': '123'},
            icn='some_icn',
        )
        formatted_payload = VETextClient.format_for_vetext(payload)
        expected_formatted_payload = {
            'appSid': DEFAULT_MOBILE_APP_TYPE,
            'icn': 'some_icn',
            'personalization': {'%FOO_1%': 'bar', '%BAZ_TWO%': 'abc', '%TMP%': '123'},
            'templateSid': 'any_template_id',
        }
        assert formatted_payload == expected_formatted_payload

    def test_format_happy_path_broadcast(self):
        payload = V2PushPayload(DEFAULT_MOBILE_APP_TYPE, 'any_template_id', topic_sid='some_topic_sid')
        formatted_payload = VETextClient.format_for_vetext(payload)
        expected_formatted_payload = {
            'appSid': DEFAULT_MOBILE_APP_TYPE,
            'personalization': None,
            'templateSid': 'any_template_id',
            'topicSid': 'some_topic_sid',
        }
        assert formatted_payload == expected_formatted_payload

    def test_format_personalisation_happy_path(self):
        payload = V2PushPayload(DEFAULT_MOBILE_APP_TYPE, 'any_template_id')
        formatted_payload = VETextClient.format_for_vetext(payload)
        expected_formatted_payload = {
            'appSid': DEFAULT_MOBILE_APP_TYPE,
            'icn': None,
            'personalization': None,
            'templateSid': 'any_template_id',
        }
        assert formatted_payload == expected_formatted_payload


class TestSendPushNotification:
    @pytest.fixture
    def sample_vetext_push_payload(self, test_vetext_client):
        """Defaults to ICN (normal push, not broadcast)"""

        def _wrapper(
            mobile_app: str = DEFAULT_MOBILE_APP_TYPE,
            template_id: str = 'any_template_id',
            icn: str | None = 'some_icn',
            topic_sid: str | None = None,
            personalisation: dict[str, str] | None = None,
        ) -> dict[str, str]:
            payload = V2PushPayload(mobile_app, template_id, icn, topic_sid, personalisation)
            return test_vetext_client.format_for_vetext(payload)

        yield _wrapper

    def test_send_push_notification_correct_request(self, rmock, test_vetext_client):
        response = {'success': True, 'statusCode': 200}
        rmock.post(ANY, json=response, status_code=200)

        mobile_app_id = sample_mobile_app_type()
        template_id = str(uuid4())
        icn = sample_recipient_identifier(IdentifierType.ICN).id_value
        personalization = {'%FOO_1%': 'bar', '%BAZ_TWO%': 'abc', '%TMP%': '123'}

        payload = {
            'icn': icn,
            'templateSid': template_id,
            'appSid': mobile_app_id,
            'personalization': personalization,
        }

        test_vetext_client.send_push_notification(payload)
        assert rmock.called

        expected_url = f'{MOCK_VETEXT_URL}/mobile/push/send'
        request = rmock.request_history[0]
        assert request.url == expected_url
        assert request.json() == {
            'appSid': mobile_app_id,
            'templateSid': template_id,
            'icn': icn,
            'personalization': personalization,
        }
        expected_auth = 'Basic ' + b64encode(bytes(f'{MOCK_USER}:{MOCK_PASSWORD}', 'utf-8')).decode('ascii')
        assert request.headers.get('Authorization') == expected_auth
        assert request.timeout == test_vetext_client.TIMEOUT

    def test_send_push_captures_statsd_metrics_on_success(self, rmock, test_vetext_client):
        response = {'success': True, 'statusCode': 200}
        rmock.post(ANY, json=response, status_code=200)

        payload = {
            'appSid': sample_mobile_app_type(),
            'templateSid': str(uuid4()),
            'icn': sample_recipient_identifier(IdentifierType.ICN).id_value,
        }

        test_vetext_client.send_push_notification(payload)

        test_vetext_client.statsd.incr.assert_called_with('clients.vetext.success')
        test_vetext_client.statsd.timing.assert_called_with('clients.vetext.request_time', mock.ANY)

    def test_send_push_notification_happy_path_icn(
        self,
        client,
        rmock,
        test_vetext_client,
        sample_vetext_push_payload,
    ):
        rmock.register_uri(
            'POST',
            f'{MOCK_VETEXT_URL}/mobile/push/send',
            json={'message': 'success'},
            status_code=201,
        )

        # Should run without exceptions
        test_vetext_client.send_push_notification(sample_vetext_push_payload())

    def test_send_push_notification_happy_path_topic(
        self,
        client,
        rmock,
        test_vetext_client,
        sample_vetext_push_payload,
    ):
        rmock.register_uri(
            'POST',
            f'{MOCK_VETEXT_URL}/mobile/push/send',
            json={'message': 'success'},
            status_code=201,
        )

        # Should run without exceptions
        test_vetext_client.send_push_notification(sample_vetext_push_payload(icn=None, topic_sid='some_topic_sid'))

    @pytest.mark.parametrize(
        'test_exception, status_code',
        [
            (ConnectTimeout(), None),
            (HTTPError(response=Response()), 429),
            (HTTPError(response=Response()), 500),
            (HTTPError(response=Response()), 502),
            (HTTPError(response=Response()), 503),
            (HTTPError(response=Response()), 504),
        ],
    )
    def test_send_push_notification_retryable_exception(
        self,
        client,
        rmock,
        test_exception,
        status_code,
        test_vetext_client,
        sample_vetext_push_payload,
    ):
        if status_code is not None:
            test_exception.response.status_code = status_code
        rmock.register_uri(
            'POST',
            f'{MOCK_VETEXT_URL}/mobile/push/send',
            exc=test_exception,
        )

        with pytest.raises(RetryableException):
            test_vetext_client.send_push_notification(sample_vetext_push_payload())

    @pytest.mark.parametrize(
        'test_exception, status_code',
        [
            (HTTPError(response=Response()), 400),
            (HTTPError(response=Response()), 403),
            (HTTPError(response=Response()), 405),
            (RequestException(), None),
        ],
    )
    def test_send_push_notification_nonretryable_exception(
        self,
        client,
        test_exception,
        status_code,
        rmock,
        test_vetext_client,
        sample_vetext_push_payload,
    ):
        if status_code is not None:
            test_exception.response.status_code = status_code
        rmock.register_uri(
            'POST',
            f'{MOCK_VETEXT_URL}/mobile/push/send',
            exc=test_exception,
        )

        with pytest.raises(NonRetryableException):
            test_vetext_client.send_push_notification(sample_vetext_push_payload())
