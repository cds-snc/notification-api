import pytest
import requests
from base64 import b64encode
from requests_mock import ANY
from unittest import mock
from uuid import uuid4
from app.va.identifier import IdentifierType
from app.va.vetext import VETextClient
from app.va.vetext.exceptions import (
    VETextException,
    VETextBadRequestException,
    VETextNonRetryableException,
    VETextRetryableException,
)
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


def test_send_push_notification_correct_request(rmock, test_vetext_client):
    response = {'success': True, 'statusCode': 200}
    rmock.post(ANY, json=response, status_code=200)

    mobile_app_id = sample_mobile_app_type()
    template_id = str(uuid4())
    icn = sample_recipient_identifier(IdentifierType.ICN)
    personalization = {'foo_1': 'bar', 'baz_two': 'abc', 'tmp': '123'}

    formatted_personalization = {'%FOO_1%': 'bar', '%BAZ_TWO%': 'abc', '%TMP%': '123'}

    test_vetext_client.send_push_notification(mobile_app_id, template_id, icn.id_value, False, personalization)
    assert rmock.called

    expected_url = f'{MOCK_VETEXT_URL}/mobile/push/send'
    request = rmock.request_history[0]
    assert request.url == expected_url
    assert request.json() == {
        'appSid': mobile_app_id,
        'templateSid': template_id,
        'icn': icn.id_value,
        'personalization': formatted_personalization,
    }
    expected_auth = 'Basic ' + b64encode(bytes(f'{MOCK_USER}:{MOCK_PASSWORD}', 'utf-8')).decode('ascii')
    assert request.headers.get('Authorization') == expected_auth
    assert request.timeout == test_vetext_client.TIMEOUT


def test_send_push_captures_statsd_metrics_on_success(rmock, test_vetext_client):
    response = {'success': True, 'statusCode': 200}
    rmock.post(ANY, json=response, status_code=200)

    mobile_app_id = sample_mobile_app_type()
    template_id = str(uuid4())
    icn = sample_recipient_identifier(IdentifierType.ICN)

    test_vetext_client.send_push_notification(mobile_app_id, template_id, icn.id_value)

    test_vetext_client.statsd.incr.assert_called_with('clients.vetext.success')
    test_vetext_client.statsd.timing.assert_called_with('clients.vetext.request_time', mock.ANY)


class TestRequestExceptions:
    def test_raises_retryable_error_on_request_exception(self, rmock, test_vetext_client):
        rmock.post(url=f'{MOCK_VETEXT_URL}/mobile/push/send', exc=requests.exceptions.ConnectTimeout)

        with pytest.raises(VETextRetryableException):
            test_vetext_client.send_push_notification(
                'app_sid',
                'template_sid',
                'icn',
            )

    def test_logs_warning_on_read_timeout(self, rmock, test_vetext_client):
        rmock.post(url=f'{MOCK_VETEXT_URL}/mobile/push/send', exc=requests.exceptions.ReadTimeout)

        test_vetext_client.send_push_notification(
            'app_sid',
            'template_sid',
            'icn',
        )
        assert test_vetext_client.logger.warning.called

    def test_increments_statsd_and_timing_on_request_exception(self, rmock, test_vetext_client):
        rmock.post(url=f'{MOCK_VETEXT_URL}/mobile/push/send', exc=requests.exceptions.ConnectTimeout)

        with pytest.raises(VETextRetryableException):
            test_vetext_client.send_push_notification(
                'app_sid',
                'template_sid',
                'icn',
            )
        test_vetext_client.statsd.incr.assert_called_with('clients.vetext.error.connection_timeout')
        test_vetext_client.statsd.timing.assert_called_with('clients.vetext.request_time', mock.ANY)


class TestHTTPExceptions:
    @pytest.mark.parametrize('http_status_code', [429, 500, 502, 503, 504])
    def test_raises_on_retryable_http_exception_and_logs(self, rmock, test_vetext_client, http_status_code):
        rmock.post(url=f'{MOCK_VETEXT_URL}/mobile/push/send', status_code=http_status_code)

        with pytest.raises(VETextRetryableException):
            test_vetext_client.send_push_notification(
                'app_sid',
                'template_sid',
                'icn',
            )
        assert test_vetext_client.logger.warning.called

    @pytest.mark.parametrize('http_status_code', [401, 404])
    def test_raises_nonretryable_on_request_exception_and_logs(self, rmock, test_vetext_client, http_status_code):
        rmock.post(url=f'{MOCK_VETEXT_URL}/mobile/push/send', status_code=http_status_code)

        with pytest.raises(VETextNonRetryableException):
            test_vetext_client.send_push_notification(
                'app_sid',
                'template_sid',
                'icn',
            )
        assert test_vetext_client.logger.critical.called

    @pytest.mark.parametrize('http_status_code', [401, 404, 429, 500, 502, 503, 504])
    def test_increments_statsd_and_timing_on_http_exception(self, rmock, test_vetext_client, http_status_code):
        rmock.post(url=f'{MOCK_VETEXT_URL}/mobile/push/send', status_code=http_status_code)

        with pytest.raises(VETextException):
            test_vetext_client.send_push_notification(
                'app_sid',
                'template_sid',
                'icn',
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

        with pytest.raises(VETextBadRequestException) as e:
            test_vetext_client.send_push_notification(
                'app_sid',
                'template_sid',
                'icn',
            )
        assert e.value.field == response.get('idType')
        assert e.value.message == response.get('error')

    def test_raises_bad_request_exception_when_400_error_not_json(self, rmock, test_vetext_client):
        response = 'Unrecognized field &quot;foo&quot; (class gov.va.med.lom.vetext.model.dto.PushNotification),'
        ' not marked as ignorable'
        rmock.post(url=f'{MOCK_VETEXT_URL}/mobile/push/send', status_code=400, text=response)

        with pytest.raises(VETextBadRequestException) as e:
            test_vetext_client.send_push_notification(
                'app_sid',
                'template_sid',
                'icn',
            )
        assert e.value.field is None
        assert e.value.message == response
