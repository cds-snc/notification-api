from collections import namedtuple
from random import randint
from uuid import uuid4

import pytest
from freezegun import freeze_time
from flask import current_app

from notifications_utils.recipients import InvalidPhoneError

import app
from app.constants import EMAIL_TYPE, LETTER_TYPE, SERVICE_PERMISSION_TYPES, SMS_TYPE
from app.feature_flags import FeatureFlag
from app.notifications.validators import (
    check_service_over_daily_message_limit,
    check_template_is_for_notification_type,
    check_template_is_active,
    service_can_send_to_recipient,
    check_service_over_api_rate_limit,
    validate_and_format_recipient,
    check_service_sms_sender_id,
    check_service_letter_contact_id,
    check_reply_to,
)

from app.v2.errors import BadRequestError, TooManyRequestsError, RateLimitError
from tests.app.factories.feature_flag import mock_feature_flag

from tests.conftest import set_config
from tests.app.db import (
    create_letter_contact,
)


# all of these tests should have redis enabled (except where we specifically disable it)
@pytest.fixture(scope='function', autouse=True)
def enable_redis(notify_api, mocker):
    # current_app.config['API_MESSAGE_LIMIT_ENABLED'] = True
    # current_app.config['REDIS_ENABLED'] = True
    with set_config(notify_api, 'REDIS_ENABLED', True):
        with set_config(notify_api, 'API_MESSAGE_LIMIT_ENABLED', True):
            mocker.patch('app.notifications.validators.redis_store.get', return_value=1)
            mocker.patch('app.notifications.validators.services_dao.fetch_todays_total_message_count', return_value=1)
            yield


class TestCheckServiceDailyLimit:
    @staticmethod
    @freeze_time('2025-05-04 11:11:11')
    @pytest.mark.parametrize('key_type', ['normal', 'team', 'test'])
    def test_should_check_message_limit_if_limiting_is_enabled(
        key_type,
        sample_service,
        mocker,
    ):
        service = sample_service()

        # override the value set in the fixture
        mocker.patch('app.notifications.validators.redis_store.get', return_value=None)
        mock_set = mocker.patch('app.notifications.validators.redis_store.set')
        mock_incr = mocker.patch('app.notifications.validators.redis_store.incr')

        check_service_over_daily_message_limit(key_type, service)

        # message limit is only enforced when the key type is not 'test'
        # and API_MESSAGE_LIMIT_ENABLED and REDIS_ENABLED are True
        if key_type == 'test':
            mock_set.assert_not_called()
            mock_incr.assert_not_called()
        else:
            mock_set.assert_called_once_with(str(service.id) + '-2025-05-04-count', 1, ex=3600)
            mock_incr.assert_called_once_with(str(service.id) + '-2025-05-04-count')

    @staticmethod
    @freeze_time('2025-05-04 11:11:11')
    def test_check_service_message_limit_increments_cache_count(sample_service, mocker):
        service = sample_service()
        mock_incr = mocker.patch('app.notifications.validators.redis_store.incr')

        # Cleaned by the template cleanup
        check_service_over_daily_message_limit('normal', service)

        mock_incr.assert_called_once_with(str(service.id) + '-2025-05-04-count')

    @staticmethod
    @pytest.mark.parametrize(
        'redis_enabled, api_limit_enabled',
        [(False, True), (True, False), (False, False)],
        ids=['redis_disabled', 'api_limit_disabled', 'both_disabled'],
    )
    def test_check_service_message_limit_does_not_check_cache_if_redis_or_api_limit_disabled(
        notify_api,
        sample_service,
        mocker,
        redis_enabled,
        api_limit_enabled,
    ) -> None:
        with set_config(notify_api, 'REDIS_ENABLED', redis_enabled):
            with set_config(notify_api, 'API_MESSAGE_LIMIT_ENABLED', api_limit_enabled):
                mock_get = mocker.patch('app.notifications.validators.redis_store.get')

                check_service_over_daily_message_limit('normal', sample_service())

                assert mock_get.not_called()

    @staticmethod
    @freeze_time('2025-05-04 11:11:11')
    def test_check_service_message_limit_raises_exception(
        notify_api,
        sample_service,
        mocker,
    ):
        mock_logger = mocker.patch('app.notifications.validators.current_app.logger.info')

        with pytest.raises(TooManyRequestsError) as e:
            check_service_over_daily_message_limit('normal', sample_service(message_limit=1))

        assert e.value.status_code == 429
        assert e.value.message == 'Exceeded send limits (1) for today'
        assert mock_logger.call_count == 1


@pytest.mark.parametrize('template_type, notification_type', [(EMAIL_TYPE, EMAIL_TYPE), (SMS_TYPE, SMS_TYPE)])
def test_check_template_is_for_notification_type_pass(template_type, notification_type):
    assert (
        check_template_is_for_notification_type(notification_type=notification_type, template_type=template_type)
        is None
    )


@pytest.mark.parametrize('template_type, notification_type', [(SMS_TYPE, EMAIL_TYPE), (EMAIL_TYPE, SMS_TYPE)])
def test_check_template_is_for_notification_type_fails_when_template_type_does_not_match_notification_type(
    template_type, notification_type
):
    with pytest.raises(BadRequestError) as e:
        check_template_is_for_notification_type(notification_type=notification_type, template_type=template_type)
    assert e.value.status_code == 400
    error_message = '{0} template is not suitable for {1} notification'.format(template_type, notification_type)
    assert e.value.message == error_message
    assert e.value.fields == [{'template': error_message}]


def test_check_template_is_active_passes(sample_template):
    assert check_template_is_active(sample_template()) is None


def test_check_template_is_active_fails(sample_template):
    template = sample_template()
    template.archived = True
    from app.dao.templates_dao import dao_update_template

    dao_update_template(template)
    with pytest.raises(BadRequestError) as e:
        check_template_is_active(template)
    assert e.value.status_code == 400
    assert e.value.message == 'Template has been deleted'
    assert e.value.fields == [{'template': 'Template has been deleted'}]


@pytest.mark.parametrize('key_type', ['test', 'normal'])
def test_service_can_send_to_recipient_passes(
    sample_service,
    key_type,
):
    trial_mode_service = sample_service(restricted=True)
    assert (
        service_can_send_to_recipient(trial_mode_service.users[0].email_address, key_type, trial_mode_service) is None
    )
    assert (
        service_can_send_to_recipient(trial_mode_service.users[0].mobile_number, key_type, trial_mode_service) is None
    )


@pytest.mark.parametrize('key_type', ['test', 'normal'])
def test_service_can_send_to_recipient_passes_for_live_service_non_team_member(key_type, sample_service):
    service = sample_service()
    assert service_can_send_to_recipient('some_other_email@test.com', key_type, service) is None
    assert service_can_send_to_recipient('07513332413', key_type, service) is None


def test_service_can_send_to_recipient_passes_for_whitelisted_recipient_passes(
    sample_service,
    sample_service_whitelist,
):
    service = sample_service()
    sample_service_whitelist(service, email_address='some_other_email@test.com')
    assert service_can_send_to_recipient('some_other_email@test.com', 'team', service) is None
    sample_service_whitelist(service, mobile_number='6502532222')
    assert service_can_send_to_recipient('6502532222', 'team', service) is None


@pytest.mark.parametrize(
    'recipient',
    [
        {'email_address': 'some_other_email@test.com'},
        {'mobile_number': '6502532223'},
    ],
)
def test_service_can_send_to_recipient_fails_when_ignoring_whitelist(
    sample_service,
    sample_service_whitelist,
    recipient,
):
    service = sample_service()
    sample_service_whitelist(service, **recipient)
    with pytest.raises(BadRequestError) as exec_info:
        service_can_send_to_recipient(
            next(iter(recipient.values())),
            'team',
            service,
            allow_whitelisted_recipients=False,
        )
    assert exec_info.value.status_code == 400
    assert exec_info.value.message == 'Can’t send to this recipient using a team-only API key'
    assert exec_info.value.fields == []


@pytest.mark.parametrize('recipient', ['07513332413', 'some_other_email@test.com'])
@pytest.mark.parametrize(
    'key_type, error_message',
    [
        ('team', 'Can’t send to this recipient using a team-only API key'),
        (
            'normal',
            'Can’t send to this recipient when service is in trial mode – see https://www.notifications.service.gov.uk/trial-mode',
        ),
    ],
)  # noqa
def test_service_can_send_to_recipient_fails_when_recipient_is_not_on_team(
    sample_service,
    recipient,
    key_type,
    error_message,
):
    trial_mode_service = sample_service(restricted=True)
    with pytest.raises(BadRequestError) as exec_info:
        service_can_send_to_recipient(recipient, key_type, trial_mode_service)
    assert exec_info.value.status_code == 400
    assert exec_info.value.message == error_message
    assert exec_info.value.fields == []


def test_service_can_send_to_recipient_fails_when_mobile_number_is_not_on_team(sample_service):
    with pytest.raises(BadRequestError) as e:
        service_can_send_to_recipient('0758964221', 'team', sample_service())
    assert e.value.status_code == 400
    assert e.value.message == 'Can’t send to this recipient using a team-only API key'
    assert e.value.fields == []


@pytest.mark.parametrize('key_type', ['team', 'live', 'test'])
def test_that_when_exceed_rate_limit_request_fails(
    key_type,
    sample_api_key,
    sample_service,
    mocker,
):
    with freeze_time('2016-01-01 12:00:00.000000'):
        current_app.config['API_RATE_LIMIT_ENABLED'] = True

        if key_type == 'live':
            api_key_type = 'normal'
        else:
            api_key_type = key_type

        mocker.patch('app.redis_store.exceeded_rate_limit', return_value=True)
        mocker.patch('app.notifications.validators.services_dao')

        service = sample_service()
        service.restricted = True
        api_key = sample_api_key(service, key_type=api_key_type)

        with pytest.raises(RateLimitError) as e:
            check_service_over_api_rate_limit(service, api_key)

        assert app.redis_store.exceeded_rate_limit.called_with(
            '{}-{}'.format(str(service.id), api_key.key_type), service.rate_limit, 60
        )
        assert e.value.status_code == 429
        assert e.value.message == 'Exceeded rate limit for key type {} of {} requests per {} seconds'.format(
            key_type.upper(), service.rate_limit, 60
        )
        assert e.value.fields == []


def test_that_when_not_exceeded_rate_limit_request_succeeds(
    sample_api_key,
    sample_service,
    mocker,
):
    with freeze_time('2016-01-01 12:00:00.000000'):
        mocker.patch('app.redis_store.exceeded_rate_limit', return_value=False)
        mocker.patch('app.notifications.validators.services_dao')

        service = sample_service()
        service.restricted = True
        api_key = sample_api_key(service)

        check_service_over_api_rate_limit(service, api_key)
        assert app.redis_store.exceeded_rate_limit.called_with(
            '{}-{}'.format(str(service.id), api_key.key_type), 3000, 60
        )


def test_should_not_rate_limit_if_limiting_is_disabled(
    sample_api_key,
    mocker,
):
    with freeze_time('2016-01-01 12:00:00.000000'):
        current_app.config['API_RATE_LIMIT_ENABLED'] = False
        api_key = sample_api_key()
        service = api_key.service

        mocker.patch('app.redis_store.exceeded_rate_limit', return_value=False)
        mocker.patch('app.notifications.validators.services_dao')

        service.restricted = True

        check_service_over_api_rate_limit(service, api_key)
        assert not app.redis_store.exceeded_rate_limit.called


@pytest.mark.parametrize('key_type', ['test', 'normal'])
def test_rejects_api_calls_with_international_numbers_if_service_does_not_allow_int_sms(
    sample_service,
    key_type,
):
    service = sample_service(service_permissions=[SMS_TYPE])
    with pytest.raises(BadRequestError) as e:
        validate_and_format_recipient('+20-12-1234-1234', key_type, service, SMS_TYPE)
    assert e.value.status_code == 400
    assert e.value.message == 'Cannot send to international mobile numbers'
    assert e.value.fields == []


@pytest.mark.parametrize('key_type', ['test', 'normal'])
def test_allows_api_calls_with_international_numbers_if_service_does_allow_int_sms(
    key_type,
    sample_service,
):
    service = sample_service(
        service_name=f'sample service full permissions {uuid4()}', service_permissions=SERVICE_PERMISSION_TYPES
    )
    result = validate_and_format_recipient('+20-12-1234-1234', key_type, service, SMS_TYPE)
    assert result == '+201212341234'


def test_rejects_api_calls_with_no_recipient():
    with pytest.raises(BadRequestError) as e:
        validate_and_format_recipient(None, 'key_type', 'service', SMS_TYPE)
    assert e.value.status_code == 400
    assert e.value.message == "Recipient can't be empty"


@pytest.mark.parametrize('key_type', ['test', 'normal'])
def test_validate_and_format_recipient_raises_with_invalid_country_code(
    key_type,
    sample_service,
):
    """Should raise InvalidPhoneError when number with country code in non-geographic region is used."""
    service = sample_service(
        service_name=f'sample service full permissions {uuid4()}', service_permissions=SERVICE_PERMISSION_TYPES
    )
    with pytest.raises(InvalidPhoneError) as e:
        validate_and_format_recipient('+80888888888', key_type, service, SMS_TYPE)
    assert str(e.value) == 'Not a valid country prefix'


@pytest.mark.parametrize('notification_type', [SMS_TYPE, EMAIL_TYPE, LETTER_TYPE])
def test_check_service_sms_sender_id_where_sms_sender_id_is_none(notification_type):
    assert check_service_sms_sender_id(None, None, notification_type) is None


def test_check_service_sms_sender_id_where_sms_sender_id_is_found(
    sample_service,
):
    number = randint(1000000, 9999999999)
    service = sample_service(sms_sender=number)
    assert check_service_sms_sender_id(service.id, service.get_default_sms_sender_id(), SMS_TYPE) == str(number)


def test_check_service_sms_sender_id_where_service_id_is_not_found(
    sample_service,
):
    fake_service_id = uuid4()
    number = randint(1000000, 9999999999)
    service = sample_service(sms_sender=number)
    sms_sender_id = service.get_default_sms_sender_id()

    with pytest.raises(BadRequestError) as e:
        check_service_sms_sender_id(fake_service_id, sms_sender_id, SMS_TYPE)
    assert e.value.status_code == 400
    assert e.value.message == 'sms_sender_id {} does not exist in database for service id {}'.format(
        sms_sender_id, fake_service_id
    )


def test_check_service_sms_sender_id_where_sms_sender_is_not_found(sample_service, fake_uuid):
    service = sample_service()
    with pytest.raises(BadRequestError) as e:
        check_service_sms_sender_id(service.id, fake_uuid, SMS_TYPE)
    assert e.value.status_code == 400
    assert e.value.message == 'sms_sender_id {} does not exist in database for service id {}'.format(
        fake_uuid, service.id
    )


def test_check_service_letter_contact_id_where_letter_contact_id_is_none():
    assert check_service_letter_contact_id(None, None, LETTER_TYPE) is None


def test_check_service_letter_contact_id_where_letter_contact_id_is_found(sample_service):
    service = sample_service()
    letter_contact = create_letter_contact(service=service, contact_block='123456')
    assert check_service_letter_contact_id(service.id, letter_contact.id, LETTER_TYPE) == '123456'


def test_check_service_letter_contact_id_where_service_id_is_not_found(sample_service, fake_uuid):
    letter_contact = create_letter_contact(service=sample_service(), contact_block='123456')
    with pytest.raises(BadRequestError) as e:
        check_service_letter_contact_id(fake_uuid, letter_contact.id, LETTER_TYPE)
    assert e.value.status_code == 400
    assert e.value.message == 'letter_contact_id {} does not exist in database for service id {}'.format(
        letter_contact.id, fake_uuid
    )


def test_check_service_letter_contact_id_where_letter_contact_is_not_found(sample_service, fake_uuid):
    service = sample_service()
    with pytest.raises(BadRequestError) as e:
        check_service_letter_contact_id(service.id, fake_uuid, LETTER_TYPE)
    assert e.value.status_code == 400
    assert e.value.message == 'letter_contact_id {} does not exist in database for service id {}'.format(
        fake_uuid, service.id
    )


@pytest.mark.parametrize('notification_type', [SMS_TYPE, EMAIL_TYPE, LETTER_TYPE])
def test_check_reply_to_with_empty_reply_to(sample_service, notification_type):
    assert check_reply_to(sample_service().id, None, notification_type) is None


def test_check_reply_to_sms_type(
    sample_service,
):
    number = randint(1000000, 9999999999)
    service = sample_service(sms_sender=number)
    assert check_reply_to(service.id, service.get_default_sms_sender_id(), SMS_TYPE) == str(number)


class TestSmsSenderRateLimit:
    def test_that_when_sms_sender_rate_exceed_rate_limit_request_fails(
        self,
        sample_service,
        mocker,
    ):
        from app.notifications.validators import check_sms_sender_over_rate_limit

        with freeze_time('2016-01-01 12:00:00.000000'):
            service = sample_service()
            mock_feature_flag(mocker, FeatureFlag.SMS_SENDER_RATE_LIMIT_ENABLED, 'True')

            MockServiceSmsSender = namedtuple(
                'ServiceSmsSender', ['id', 'rate_limit', 'rate_limit_interval', 'sms_sender']
            )
            sms_sender = MockServiceSmsSender(
                id='some-id', rate_limit=3000, rate_limit_interval=60, sms_sender='+18888888888'
            )

            should_throttle = mocker.patch(
                'app.notifications.validators.redis_store.should_throttle', return_value=True
            )
            mocker.patch('app.notifications.validators.services_dao')
            mocker.patch('app.notifications.validators.dao_get_service_sms_sender_by_id', return_value=sms_sender)

            service.restricted = True

            with pytest.raises(RateLimitError) as e:
                check_sms_sender_over_rate_limit(service, sms_sender)

            should_throttle.assert_called_once_with(sms_sender.sms_sender, service.rate_limit, 60)
            assert e.value.status_code == 429
            assert e.value.message == (f'Exceeded rate limit of {sms_sender.rate_limit} requests per 60 seconds')
            assert e.value.fields == []

    def test_that_when_not_exceeded_sms_sender_rate_limit_request_succeeds(self, sample_service, mocker):
        from app.notifications.validators import check_sms_sender_over_rate_limit

        with freeze_time('2016-01-01 12:00:00.000000'):
            service = sample_service()
            mock_feature_flag(mocker, FeatureFlag.SMS_SENDER_RATE_LIMIT_ENABLED, 'True')
            MockServiceSmsSender = namedtuple(
                'ServiceSmsSender', ['id', 'sms_sender', 'rate_limit', 'rate_limit_interval']
            )
            sms_sender = MockServiceSmsSender(
                id='some-id', sms_sender='+11111111111', rate_limit=10, rate_limit_interval=60
            )

            should_throttle = mocker.patch(
                'app.notifications.validators.redis_store.should_throttle', return_value=False
            )
            mocker.patch('app.notifications.validators.services_dao')
            mocker.patch('app.notifications.validators.dao_get_service_sms_sender_by_id', return_value=sms_sender)

            service.restricted = True

            check_sms_sender_over_rate_limit(service, sms_sender)
            should_throttle.assert_called_once_with(str(sms_sender.sms_sender), 10, 60)


class TestTemplateNameAlreadyExistsOnService:
    def test_that_template_name_already_exists_on_service_returns_true(self, mocker):
        from app.notifications.validators import template_name_already_exists_on_service

        mocker.patch('app.notifications.validators.dao_get_number_of_templates_by_service_id_and_name', return_value=1)

        assert template_name_already_exists_on_service('some service id', 'some template name')

    def test_that_template_name_already_exists_on_service_returns_false(self, mocker):
        from app.notifications.validators import template_name_already_exists_on_service

        mocker.patch('app.notifications.validators.dao_get_number_of_templates_by_service_id_and_name', return_value=0)

        assert not template_name_already_exists_on_service('some service id', 'some template name')
