from unittest.mock import call

import pytest
from flask import current_app
from freezegun import freeze_time
from notifications_utils import SMS_CHAR_COUNT_LIMIT

import app
from app.dbsetup import RoutingSQLAlchemy
from app.models import (
    EMAIL_TYPE,
    INTERNATIONAL_SMS_TYPE,
    KEY_TYPE_TEAM,
    LETTER_TYPE,
    SMS_TYPE,
    ApiKeyType,
)
from app.notifications.validators import (
    check_email_annual_limit,
    check_email_daily_limit,
    check_reply_to,
    check_service_email_reply_to_id,
    check_service_letter_contact_id,
    check_service_over_api_rate_limit_and_update_rate,
    check_service_over_daily_message_limit,
    check_service_sms_sender_id,
    check_sms_annual_limit,
    check_sms_content_char_count,
    check_sms_daily_limit,
    check_template_is_active,
    check_template_is_for_notification_type,
    increment_email_daily_count_send_warnings_if_needed,
    increment_sms_daily_count_send_warnings_if_needed,
    service_can_send_to_recipient,
    validate_and_format_recipient,
)
from app.utils import get_document_url
from app.v2.errors import (
    BadRequestError,
    LiveServiceRequestExceedsEmailAnnualLimitError,
    LiveServiceRequestExceedsSMSAnnualLimitError,
    RateLimitError,
    TooManyEmailRequestsError,
    TooManyRequestsError,
    TooManySMSRequestsError,
    TrialServiceRequestExceedsEmailAnnualLimitError,
    TrialServiceRequestExceedsSMSAnnualLimitError,
)
from tests.app.conftest import (
    create_sample_api_key,
    create_sample_notification,
    create_sample_service,
    create_sample_service_safelist,
    create_sample_template,
)
from tests.app.db import (
    create_ft_notification_status,
    create_letter_contact,
    create_reply_to_email,
    create_service_sms_sender,
)
from tests.conftest import set_config


# all of these tests should have redis enabled (except where we specifically disable it)
@pytest.fixture(scope="module", autouse=True)
def enable_redis(notify_api):
    with set_config(notify_api, "REDIS_ENABLED", True):
        yield


def count_key(limit_type, service_id):
    if limit_type == "sms":
        return f"sms-{service_id}-2016-01-01-count"
    elif limit_type == "email":
        return f"email-{service_id}-2016-01-01-count"
    else:
        return f"{service_id}-2016-01-01-count"


def near_key(limit_type, service_id):
    if limit_type == "sms":
        return f"nearing-daily-limit-sms-{service_id}-2016-01-01-count"
    elif limit_type == "email":
        return f"nearing-daily-email-limit-email-{service_id}-2016-01-01-count"
    else:
        return f"nearing-{service_id}-2016-01-01-count"


def over_key(limit_type, service_id):
    if limit_type == "sms":
        return f"over-daily-limit-sms-{service_id}-2016-01-01-count"
    elif limit_type == "email":
        return f"over-daily-email-limit-email-{service_id}-2016-01-01-count"
    else:
        return f"over-{service_id}-2016-01-01-count"


class TestCheckDailySMSEmailLimits:
    @pytest.mark.parametrize(
        "limit_type",
        ["email", "sms"],
    )
    def test_check_service_message_limit_in_cache_with_unrestricted_service_is_allowed(
        self, notify_api, limit_type, sample_service, mocker
    ):
        mocker.patch("app.notifications.validators.redis_store.get", return_value=1)
        mocker.patch("app.notifications.validators.redis_store.set")
        mocker.patch("app.notifications.validators.services_dao")
        if limit_type == "sms":
            check_sms_daily_limit(sample_service)
        else:
            check_email_daily_limit(sample_service)
        app.notifications.validators.redis_store.set.assert_not_called()
        assert not app.notifications.validators.services_dao.mock_calls

    @pytest.mark.parametrize(
        "limit_type",
        ["email", "sms"],
    )
    def test_check_service_message_limit_in_cache_under_message_limit_passes(
        self, notify_api, limit_type, sample_service, mocker
    ):
        mocker.patch("app.notifications.validators.redis_store.get", return_value=1)
        mocker.patch("app.notifications.validators.redis_store.set")
        mocker.patch("app.notifications.validators.services_dao")
        if limit_type == "sms":
            check_sms_daily_limit(sample_service)
        else:
            check_email_daily_limit(sample_service)
            app.notifications.validators.redis_store.set.assert_not_called()
        assert not app.notifications.validators.services_dao.mock_calls

    def test_should_not_interact_with_cache_for_test_key(self, notify_api, sample_service, mocker):
        mocker.patch("app.notifications.validators.redis_store")
        check_service_over_daily_message_limit("test", sample_service)
        assert not app.notifications.validators.redis_store.mock_calls

    @pytest.mark.parametrize(
        "key_type",
        ["team", "normal"],
    )
    def test_should_set_cache_value_as_value_from_database_if_cache_not_set(
        self, notify_api, key_type, notify_db, notify_db_session, sample_service, mocker
    ):
        with freeze_time("2016-01-01 12:00:00.000000"):
            for x in range(5):
                create_sample_notification(notify_db, notify_db_session, service=sample_service, billable_units=2)
            mocker.patch("app.notifications.validators.redis_store.get", return_value=None)
            mocker.patch("app.notifications.validators.redis_store.set")

            check_service_over_daily_message_limit(key_type, sample_service)

            app.notifications.validators.redis_store.set.assert_called_with(count_key("all", sample_service.id), 5, ex=7200)

    def test_should_not_access_database_if_redis_disabled(self, notify_api, sample_service, mocker):
        with set_config(notify_api, "REDIS_ENABLED", False):
            db_mock = mocker.patch("app.notifications.validators.services_dao")
            check_service_over_daily_message_limit("normal", sample_service)
            check_sms_daily_limit(sample_service)

            assert db_mock.method_calls == []

    @pytest.mark.parametrize(
        "key_type, email_template",
        [
            ("team", "REACHED_DAILY_LIMIT_TEMPLATE_ID"),
            ("normal", "REACHED_DAILY_LIMIT_TEMPLATE_ID"),
        ],
    )
    def test_check_service_message_limit_over_message_limit_fails(
        self, notify_api, key_type, email_template, notify_db, notify_db_session, mocker
    ):
        with freeze_time("2016-01-01 12:00:00.000000"):
            redis_get = mocker.patch("app.redis_store.get", side_effect=["5", True, None])
            redis_set = mocker.patch("app.redis_store.set")
            send_notification = mocker.patch("app.notifications.validators.send_notification_to_service_users")
            service = create_sample_service(notify_db, notify_db_session, restricted=True, limit=4)
            for x in range(5):
                create_sample_notification(notify_db, notify_db_session, service=service)

            with pytest.raises(TooManyRequestsError) as e:
                check_service_over_daily_message_limit(key_type, service)
            assert e.value.message == "Exceeded send limits (4) for today"
            assert e.value.status_code == 429
            assert e.value.fields == []

            assert redis_get.call_args_list == [
                call(count_key("all", service.id)),
                call(near_key("all", service.id)),
                call(over_key("all", service.id)),
            ]

            assert redis_set.call_args_list == [call(over_key("all", service.id), "2016-01-01T12:00:00", ex=86400)]

            send_notification.assert_called_once_with(
                service_id=service.id,
                template_id=current_app.config[email_template],
                personalisation={
                    "service_name": service.name,
                    "contact_url": f"{current_app.config['ADMIN_BASE_URL']}/contact",
                    "message_limit_en": "4",
                    "message_limit_fr": "4",
                },
                include_user_fields=["name"],
            )

    @pytest.mark.parametrize(
        "limit_type, template_name",
        [("email", "NEAR_DAILY_EMAIL_LIMIT_TEMPLATE_ID"), ("sms", "NEAR_DAILY_SMS_LIMIT_TEMPLATE_ID")],
    )
    def test_check_service_message_limit_records_nearing_daily_limit(
        self, notify_api, limit_type, template_name, notify_db, notify_db_session, mocker
    ):
        with freeze_time("2016-01-01 12:00:00.000000"):
            redis_get = mocker.patch("app.redis_store.get", side_effect=[4, 4, None])
            send_notification = mocker.patch("app.notifications.validators.send_notification_to_service_users")

            service = create_sample_service(notify_db, notify_db_session, restricted=True, limit=5, sms_limit=5)
            template = create_sample_template(notify_db, notify_db_session, service=service, template_type=limit_type)
            for x in range(5):
                create_sample_notification(notify_db, notify_db_session, service=service, template=template)

            if limit_type == "sms":
                increment_sms_daily_count_send_warnings_if_needed(service)
            else:
                increment_email_daily_count_send_warnings_if_needed(service)

            assert redis_get.call_args_list == [
                call(count_key(limit_type, service.id)),
                call(count_key(limit_type, service.id)),
                call(near_key(limit_type, service.id)),
            ]
            kwargs = {"limit_reset_time_et_12hr": "7PM", "limit_reset_time_et_24hr": "19"}
            send_notification.assert_called_once_with(
                service_id=service.id,
                template_id=current_app.config[template_name],
                personalisation={
                    "service_name": service.name,
                    "contact_url": f"{current_app.config['ADMIN_BASE_URL']}/contact",
                    "count_en": "4",
                    "count_fr": "4",
                    "remaining_en": "1",
                    "remaining_fr": "1",
                    "message_limit_en": "5",
                    "message_limit_fr": "5",
                    **kwargs,
                },
                include_user_fields=["name"],
            )

    def test_check_service_message_limit_does_not_send_notifications_if_already_did(
        self, notify_api, notify_db, notify_db_session, mocker
    ):
        with freeze_time("2016-01-01 12:00:00.000000"):
            redis_get = mocker.patch("app.redis_store.get", side_effect=[5, True, True])
            redis_set = mocker.patch("app.redis_store.set")
            send_notification = mocker.patch("app.notifications.validators.send_notification_to_service_users")

            service = create_sample_service(notify_db, notify_db_session, restricted=True, limit=5, sms_limit=5)

            with pytest.raises(TooManyRequestsError) as e:
                check_service_over_daily_message_limit("normal", service)
            assert e.value.message == "Exceeded send limits (5) for today"
            assert e.value.status_code == 429
            assert e.value.fields == []

            assert redis_get.call_args_list == [
                call(count_key("all", service.id)),
                call(near_key("all", service.id)),
                call(over_key("all", service.id)),
            ]
            redis_set.assert_not_called()
            send_notification.assert_not_called()

    @pytest.mark.parametrize("key_type", ["team", "normal"])
    def test_check_service_message_limit_in_cache_over_message_limit_fails(
        self, notify_api, notify_db, notify_db_session, key_type, mocker
    ):
        with freeze_time("2016-01-01 12:00:00.000000"):
            mocker.patch("app.redis_store.get", return_value=5)
            mocker.patch("app.notifications.validators.redis_store.set")
            mocker.patch("app.notifications.validators.services_dao")

            service = create_sample_service(notify_db, notify_db_session, restricted=True, limit=4, sms_limit=4)
            with pytest.raises(TooManyRequestsError) as e:
                check_service_over_daily_message_limit(key_type, service)
            assert e.value.status_code == 429
            assert e.value.message == "Exceeded send limits (4) for today"
            assert e.value.fields == []

            with pytest.raises(TooManySMSRequestsError) as e:
                check_sms_daily_limit(service)
            assert e.value.status_code == 429
            assert e.value.message == "Exceeded SMS daily sending limit of 4 fragments"
            assert e.value.fields == []

            with pytest.raises(TooManyEmailRequestsError) as e:
                check_email_daily_limit(service)
            assert e.value.status_code == 429
            assert e.value.message == "Exceeded email daily sending limit of 4 messages"
            assert e.value.fields == []

            app.notifications.validators.redis_store.set.assert_not_called()
            assert not app.notifications.validators.services_dao.mock_calls

    @pytest.mark.parametrize(
        "is_trial_service, expected_counter",
        [
            (True, "validators.rate_limit.trial_service_daily"),
            (False, "validators.rate_limit.live_service_daily"),
        ],
        ids=["trial service", "live service"],
    )
    def test_check_service_message_limit_sends_statsd_over_message_limit_fails(
        self,
        notify_api,
        app_statsd,
        notify_db,
        notify_db_session,
        mocker,
        is_trial_service,
        expected_counter,
    ):
        mocker.patch("app.redis_store.get", return_value=5)
        mocker.patch("app.notifications.validators.redis_store.set")

        service = create_sample_service(notify_db, notify_db_session, restricted=is_trial_service, limit=4, sms_limit=4)

        with pytest.raises(TooManyRequestsError):
            check_service_over_daily_message_limit("normal", service)

        app_statsd.statsd_client.incr.assert_called_once_with(expected_counter)

    def test_check_service_message_limit_skip_statsd_over_message_no_limit_fails_sms(
        self, notify_api, app_statsd, notify_db, notify_db_session, mocker
    ):
        # Given
        mocker.patch("app.redis_store.get", return_value=0)
        mocker.patch("app.notifications.validators.redis_store.set")

        # When
        service = create_sample_service(notify_db, notify_db_session, restricted=True, limit=4, sms_limit=4)
        check_service_over_daily_message_limit("normal", service)
        check_sms_daily_limit(service)
        # Then
        app_statsd.statsd_client.incr.assert_not_called()

    def test_check_service_message_limit_skip_statsd_over_message_no_limit_fails_emails(
        self, notify_api, app_statsd, notify_db, notify_db_session, mocker
    ):
        # Given
        mocker.patch("app.redis_store.get", return_value=0)
        mocker.patch("app.notifications.validators.redis_store.set")

        # When
        service = create_sample_service(notify_db, notify_db_session, restricted=True, limit=4, sms_limit=4)
        check_email_daily_limit(service)

        # Then
        app_statsd.statsd_client.incr.assert_not_called()


@pytest.mark.parametrize("template_type, notification_type", [(EMAIL_TYPE, EMAIL_TYPE), (SMS_TYPE, SMS_TYPE)])
def test_check_template_is_for_notification_type_pass(template_type, notification_type):
    assert check_template_is_for_notification_type(notification_type=notification_type, template_type=template_type) is None


@pytest.mark.parametrize("template_type, notification_type", [(SMS_TYPE, EMAIL_TYPE), (EMAIL_TYPE, SMS_TYPE)])
def test_check_template_is_for_notification_type_fails_when_template_type_does_not_match_notification_type(
    template_type, notification_type
):
    with pytest.raises(BadRequestError) as e:
        check_template_is_for_notification_type(notification_type=notification_type, template_type=template_type)
    assert e.value.status_code == 400
    error_message = "{0} template is not suitable for {1} notification".format(template_type, notification_type)
    assert e.value.message == error_message
    assert e.value.fields == [{"template": error_message}]


def test_check_template_is_active_passes(sample_template):
    assert check_template_is_active(sample_template) is None


def test_check_template_is_active_fails(sample_template):
    sample_template.archived = True
    from app.dao.templates_dao import dao_update_template

    dao_update_template(sample_template)
    with pytest.raises(BadRequestError) as e:
        check_template_is_active(sample_template)
    assert e.value.status_code == 400
    assert e.value.message == f"Template {sample_template.id} has been deleted"
    assert e.value.fields == [{"template": f"Template {sample_template.id} has been deleted"}]


@pytest.mark.parametrize("key_type", ["test", "normal"])
def test_service_can_send_to_recipient_passes(key_type, notify_db, notify_db_session):
    trial_mode_service = create_sample_service(notify_db, notify_db_session, service_name="trial mode", restricted=True)
    assert service_can_send_to_recipient(trial_mode_service.users[0].email_address, key_type, trial_mode_service) is None
    assert service_can_send_to_recipient(trial_mode_service.users[0].mobile_number, key_type, trial_mode_service) is None


@pytest.mark.parametrize("key_type", ["test", "normal"])
def test_service_can_send_to_recipient_passes_for_live_service_non_team_member(key_type, notify_db, notify_db_session):
    live_service = create_sample_service(notify_db, notify_db_session, service_name="live", restricted=False)
    assert service_can_send_to_recipient("some_other_email@test.com", key_type, live_service) is None
    assert service_can_send_to_recipient("07513332413", key_type, live_service) is None


def test_service_can_send_to_recipient_passes_for_safelisted_recipient_passes(notify_db, notify_db_session, sample_service):
    create_sample_service_safelist(notify_db, notify_db_session, email_address="some_other_email@test.com")
    assert service_can_send_to_recipient("some_other_email@test.com", "team", sample_service) is None
    create_sample_service_safelist(notify_db, notify_db_session, mobile_number="6502532222")
    assert service_can_send_to_recipient("6502532222", "team", sample_service) is None


def test_service_can_send_to_recipient_passes_for_simulated_recipients(notify_db, notify_db_session):
    live_service = create_sample_service(notify_db, notify_db_session, service_name="live", restricted=False)
    assert service_can_send_to_recipient(current_app.config["SIMULATED_EMAIL_ADDRESSES"][0], KEY_TYPE_TEAM, live_service) is None
    assert service_can_send_to_recipient(current_app.config["SIMULATED_SMS_NUMBERS"][0], KEY_TYPE_TEAM, live_service) is None


@pytest.mark.parametrize(
    "recipient",
    [
        {"email_address": "some_other_email@test.com"},
        {"mobile_number": "6502532223"},
    ],
)
def test_service_can_send_to_recipient_fails_when_ignoring_safelist(
    notify_db,
    notify_db_session,
    sample_service,
    recipient,
):
    create_sample_service_safelist(notify_db, notify_db_session, **recipient)
    with pytest.raises(BadRequestError) as exec_info:
        service_can_send_to_recipient(
            next(iter(recipient.values())),
            "team",
            sample_service,
            allow_safelisted_recipients=False,
        )
    assert exec_info.value.status_code == 400
    assert (
        exec_info.value.message == f"Can’t send to this recipient using a team-only API key (service {sample_service.id}) "
        f'- see {get_document_url("en", "keys.html#team-and-safelist")}'
    )
    assert exec_info.value.fields == []


@pytest.mark.parametrize("recipient", ["07513332413", "some_other_email@test.com"])
@pytest.mark.parametrize(
    "key_type, error_message",
    [
        ("team", "Can’t send to this recipient using a team-only API key"),
        ("normal", "Can’t send to this recipient when service is in trial mode – see "),
    ],
)  # noqa
def test_service_can_send_to_recipient_fails_when_recipient_is_not_on_team(
    recipient: str,
    key_type: ApiKeyType,
    error_message: str,
    notify_db: RoutingSQLAlchemy,
    notify_db_session: RoutingSQLAlchemy,
):
    trial_mode_service = create_sample_service(notify_db, notify_db_session, service_name="trial mode", restricted=True)
    with pytest.raises(BadRequestError) as exec_info:
        service_can_send_to_recipient(recipient, key_type, trial_mode_service)
    assert exec_info.value.status_code == 400
    assert error_message in exec_info.value.message, f"Unexpected error message: {exec_info.value.message}"
    assert exec_info.value.fields == []


def test_service_can_send_to_recipient_fails_when_mobile_number_is_not_on_team(notify_db, notify_db_session):
    live_service = create_sample_service(notify_db, notify_db_session, service_name="live mode", restricted=False)
    with pytest.raises(BadRequestError) as e:
        service_can_send_to_recipient("0758964221", "team", live_service)
    assert e.value.status_code == 400
    assert (
        e.value.message == f"Can’t send to this recipient using a team-only API key (service {live_service.id}) "
        f'- see {get_document_url("en", "keys.html#team-and-safelist")}'
    )
    assert e.value.fields == []


@pytest.mark.parametrize("char_count", [612, 0, 494, 200])
def test_check_sms_content_char_count_passes(char_count, notify_api):
    assert check_sms_content_char_count(char_count, "", False) is None


@pytest.mark.parametrize("char_count", [613, 700, 6000])
def test_check_sms_content_char_count_fails(char_count, notify_api):
    with pytest.raises(BadRequestError) as e:
        check_sms_content_char_count(char_count, "", False)
    assert e.value.status_code == 400
    assert e.value.message == "Content for template has a character count greater than the limit of {}".format(
        SMS_CHAR_COUNT_LIMIT
    )
    assert e.value.fields == []


@pytest.mark.parametrize("char_count", [603, 0, 494, 200])
def test_check_sms_content_char_count_passes_with_svc_name(char_count, notify_api):
    assert check_sms_content_char_count(char_count, "service", True) is None


@pytest.mark.parametrize("char_count", [606, 700, 6000])
def test_check_sms_content_char_count_fails_with_svc_name(char_count, notify_api):
    with pytest.raises(BadRequestError) as e:
        check_sms_content_char_count(char_count, "service", True)
    assert e.value.status_code == 400
    assert e.value.message == "Content for template has a character count greater than the limit of {}".format(
        SMS_CHAR_COUNT_LIMIT
    )
    assert e.value.fields == []


@pytest.mark.parametrize("key_type", ["team", "live", "test"])
def test_that_when_exceed_rate_limit_request_fails(notify_db, notify_db_session, key_type, mocker):
    with freeze_time("2016-01-01 12:00:00.000000"):
        if key_type == "live":
            api_key_type = "normal"
        else:
            api_key_type = key_type

        mocker.patch("app.redis_store.exceeded_rate_limit", return_value=True)
        mocker.patch("app.notifications.validators.services_dao")

        service = create_sample_service(notify_db, notify_db_session, restricted=True)
        api_key = create_sample_api_key(notify_db, notify_db_session, service=service, key_type=api_key_type)
        with pytest.raises(RateLimitError) as e:
            check_service_over_api_rate_limit_and_update_rate(service, api_key)

        app.redis_store.exceeded_rate_limit.assert_called_with(
            "{}-{}".format(str(service.id), api_key.key_type), service.rate_limit, 60
        )
        assert e.value.status_code == 429
        assert e.value.message == "Exceeded rate limit for key type {} of {} requests per {} seconds".format(
            key_type.upper(), service.rate_limit, 60
        )
        assert e.value.fields == []


def test_that_when_not_exceeded_rate_limit_request_succeeds(notify_db, notify_db_session, mocker):
    with freeze_time("2016-01-01 12:00:00.000000"):
        mocker.patch("app.redis_store.exceeded_rate_limit", return_value=False)
        mocker.patch("app.notifications.validators.services_dao")

        service = create_sample_service(notify_db, notify_db_session, restricted=True)
        api_key = create_sample_api_key(notify_db, notify_db_session, service=service, key_type="normal")

        check_service_over_api_rate_limit_and_update_rate(service, api_key)
        app.redis_store.exceeded_rate_limit.assert_called_with("{}-{}".format(str(service.id), api_key.key_type), 1000, 60)


def test_should_not_rate_limit_if_limiting_is_disabled(notify_db, notify_db_session, mocker):
    with freeze_time("2016-01-01 12:00:00.000000"):
        current_app.config["API_RATE_LIMIT_ENABLED"] = False

        mocker.patch("app.redis_store.exceeded_rate_limit", return_value=False)
        mocker.patch("app.notifications.validators.services_dao")

        service = create_sample_service(notify_db, notify_db_session, restricted=True)
        api_key = create_sample_api_key(notify_db, notify_db_session, service=service)

        check_service_over_api_rate_limit_and_update_rate(service, api_key)
        assert not app.redis_store.exceeded_rate_limit.called


@pytest.mark.parametrize("key_type", ["test", "normal"])
def test_rejects_api_calls_with_international_numbers_if_service_does_not_allow_int_sms(
    key_type,
    notify_db,
    notify_db_session,
):
    service = create_sample_service(notify_db, notify_db_session, permissions=[SMS_TYPE])
    with pytest.raises(BadRequestError) as e:
        validate_and_format_recipient("+20-12-1234-1234", key_type, service, SMS_TYPE)
    assert e.value.status_code == 400
    assert e.value.message == "Cannot send to international mobile numbers"
    assert e.value.fields == []


@pytest.mark.parametrize("key_type", ["test", "normal"])
def test_allows_api_calls_with_international_numbers_if_service_does_allow_int_sms(key_type, notify_db, notify_db_session):
    service = create_sample_service(notify_db, notify_db_session, permissions=[SMS_TYPE, INTERNATIONAL_SMS_TYPE])
    result = validate_and_format_recipient("+20-12-1234-1234", key_type, service, SMS_TYPE)
    assert result == "+201212341234"


def test_rejects_api_calls_with_no_recipient():
    with pytest.raises(BadRequestError) as e:
        validate_and_format_recipient(None, "key_type", "service", "SMS_TYPE")
    assert e.value.status_code == 400
    assert e.value.message == "Recipient can't be empty"


@pytest.mark.parametrize("notification_type", ["sms", "email", "letter"])
def test_check_service_email_reply_to_id_where_reply_to_id_is_none(notification_type):
    assert check_service_email_reply_to_id(None, None, notification_type) is None


def test_check_service_email_reply_to_where_email_reply_to_is_found(sample_service):
    reply_to_address = create_reply_to_email(sample_service, "test@test.com")
    assert check_service_email_reply_to_id(sample_service.id, reply_to_address.id, EMAIL_TYPE) == "test@test.com"


def test_check_service_email_reply_to_id_where_service_id_is_not_found(sample_service, fake_uuid):
    reply_to_address = create_reply_to_email(sample_service, "test@test.com")
    with pytest.raises(BadRequestError) as e:
        check_service_email_reply_to_id(fake_uuid, reply_to_address.id, EMAIL_TYPE)
    assert e.value.status_code == 400
    assert e.value.message == "email_reply_to_id {} does not exist in database for service id {}".format(
        reply_to_address.id, fake_uuid
    )


def test_check_service_email_reply_to_id_where_reply_to_id_is_not_found(sample_service, fake_uuid):
    with pytest.raises(BadRequestError) as e:
        check_service_email_reply_to_id(sample_service.id, fake_uuid, EMAIL_TYPE)
    assert e.value.status_code == 400
    assert e.value.message == "email_reply_to_id {} does not exist in database for service id {}".format(
        fake_uuid, sample_service.id
    )


@pytest.mark.parametrize("notification_type", ["sms", "email", "letter"])
def test_check_service_sms_sender_id_where_sms_sender_id_is_none(notification_type):
    assert check_service_sms_sender_id(None, None, notification_type) is None


def test_check_service_sms_sender_id_where_sms_sender_id_is_found(sample_service):
    sms_sender = create_service_sms_sender(service=sample_service, sms_sender="123456")
    assert check_service_sms_sender_id(sample_service.id, sms_sender.id, SMS_TYPE) == "123456"


def test_check_service_sms_sender_id_where_service_id_is_not_found(sample_service, fake_uuid):
    sms_sender = create_service_sms_sender(service=sample_service, sms_sender="123456")
    with pytest.raises(BadRequestError) as e:
        check_service_sms_sender_id(fake_uuid, sms_sender.id, SMS_TYPE)
    assert e.value.status_code == 400
    assert e.value.message == "sms_sender_id {} does not exist in database for service id {}".format(sms_sender.id, fake_uuid)


def test_check_service_sms_sender_id_where_sms_sender_is_not_found(sample_service, fake_uuid):
    with pytest.raises(BadRequestError) as e:
        check_service_sms_sender_id(sample_service.id, fake_uuid, SMS_TYPE)
    assert e.value.status_code == 400
    assert e.value.message == "sms_sender_id {} does not exist in database for service id {}".format(fake_uuid, sample_service.id)


@pytest.mark.skip(reason="Letter tests")
def test_check_service_letter_contact_id_where_letter_contact_id_is_none():
    assert check_service_letter_contact_id(None, None, "letter") is None


@pytest.mark.skip(reason="Letter tests")
def test_check_service_letter_contact_id_where_letter_contact_id_is_found(
    sample_service,
):
    letter_contact = create_letter_contact(service=sample_service, contact_block="123456")
    assert check_service_letter_contact_id(sample_service.id, letter_contact.id, LETTER_TYPE) == "123456"


@pytest.mark.skip(reason="Letter tests")
def test_check_service_letter_contact_id_where_service_id_is_not_found(sample_service, fake_uuid):
    letter_contact = create_letter_contact(service=sample_service, contact_block="123456")
    with pytest.raises(BadRequestError) as e:
        check_service_letter_contact_id(fake_uuid, letter_contact.id, LETTER_TYPE)
    assert e.value.status_code == 400
    assert e.value.message == "letter_contact_id {} does not exist in database for service id {}".format(
        letter_contact.id, fake_uuid
    )


@pytest.mark.skip(reason="Letter tests")
def test_check_service_letter_contact_id_where_letter_contact_is_not_found(sample_service, fake_uuid):
    with pytest.raises(BadRequestError) as e:
        check_service_letter_contact_id(sample_service.id, fake_uuid, LETTER_TYPE)
    assert e.value.status_code == 400
    assert e.value.message == "letter_contact_id {} does not exist in database for service id {}".format(
        fake_uuid, sample_service.id
    )


@pytest.mark.parametrize("notification_type", ["sms", "email", "letter"])
def test_check_reply_to_with_empty_reply_to(sample_service, notification_type):
    assert check_reply_to(sample_service.id, None, notification_type) is None


def test_check_reply_to_email_type(sample_service):
    reply_to_address = create_reply_to_email(sample_service, "test@test.com")
    assert check_reply_to(sample_service.id, reply_to_address.id, EMAIL_TYPE) == "test@test.com"


def test_check_reply_to_sms_type(sample_service):
    sms_sender = create_service_sms_sender(service=sample_service, sms_sender="123456")
    assert check_reply_to(sample_service.id, sms_sender.id, SMS_TYPE) == "123456"


def test_check_reply_to_letter_type(sample_service):
    letter_contact = create_letter_contact(service=sample_service, contact_block="123456")
    assert check_reply_to(sample_service.id, letter_contact.id, LETTER_TYPE) == "123456"


class TestAnnualLimitValidators:
    @freeze_time("2024-11-26")
    @pytest.mark.parametrize(
        "annual_limit, counts_from_redis, do_ft_insert, ft_count, notifications_requested, will_raise, has_sent_reached_limit_email, has_sent_near_limit_email, log_msg",
        [
            (100, 81, False, 0, 20, True, False, True, "is exceeding their annual email limit"),
            (100, 0, True, 100, 5, True, False, True, "is exceeding their annual email limit"),
            (100, 50, True, 50, 1, True, False, True, "is exceeding their annual email limit"),
            (100, 5, True, 50, 5, False, False, False, None),
            (100, 50, True, 29, 5, False, False, True, "reached 80% of their annual email limit of"),
            (100, 5, True, 50, 5, False, True, False, "reached their annual email limit of"),
        ],
        ids=[
            " Cache only - Service attempts to go over annual limit",
            " DB only - Service exceeded annual limit - attempts more sends",
            " Cache & DB - Service attempts to go over annual limit",
            " Cache only - Within annual limit - not near or over limit",
            " DB only - Within annual limit - near limit",
            " Cache & DB - Within annual limit - reaches limit with current send",
        ],
    )
    @pytest.mark.parametrize(
        "is_trial_service, exception_type",
        [(True, TrialServiceRequestExceedsEmailAnnualLimitError), (False, LiveServiceRequestExceedsEmailAnnualLimitError)],
        ids=["Trial service ", "Live service "],
    )
    def test_check_email_annual_limit(
        self,
        notify_api,
        notify_db,
        notify_db_session,
        annual_limit,
        counts_from_redis,
        do_ft_insert,
        ft_count,
        is_trial_service,
        exception_type,
        notifications_requested,
        will_raise,
        has_sent_reached_limit_email,
        has_sent_near_limit_email,
        log_msg,
        mocker,
    ):
        mock_logger = mocker.patch("app.notifications.validators.current_app.logger.info")
        mock_redis_set = mocker.patch("app.redis_store.set_hash_value")  # Set over / near limit keys
        mocker.patch("app.redis_store.get", return_value=counts_from_redis)  # notifications fetched from Redis
        mocker.patch("app.annual_limit_client.check_has_warning_been_sent", return_value=has_sent_near_limit_email)
        mocker.patch(
            "app.annual_limit_client.check_has_warning_been_sent", return_value=has_sent_reached_limit_email
        )  # Email sent flag checks
        mocker.patch("app.notifications.validators.send_notification_to_service_users")
        is_near = (counts_from_redis + ft_count + notifications_requested) >= (annual_limit * 0.8)
        is_reached = (counts_from_redis + ft_count + notifications_requested) == annual_limit

        service = create_sample_service(
            notify_db, notify_db_session, restricted=is_trial_service, email_annual_limit=annual_limit
        )
        email_template = create_sample_template(notify_db, notify_db_session, template_type=EMAIL_TYPE)
        sms_template = create_sample_template(notify_db, notify_db_session, template_type=SMS_TYPE)

        if do_ft_insert:
            # Previous fiscal year
            create_ft_notification_status(
                utc_date="2024-03-31",
                service=service,
                template=email_template,
                notification_type=EMAIL_TYPE,
            )
            # Within current fiscal year
            create_ft_notification_status(
                utc_date="2024-04-01", service=service, template=email_template, notification_type=EMAIL_TYPE, count=ft_count
            )
            # In the next fiscal year
            create_ft_notification_status(
                utc_date="2025-04-01", service=service, template=email_template, notification_type=EMAIL_TYPE
            )
            # Make sure we're not counting non-email notifications
            create_ft_notification_status(
                utc_date="2024-04-01", service=service, template=sms_template, notification_type=SMS_TYPE
            )

        with set_config(notify_api, "FF_ANNUAL_LIMIT", True):
            if will_raise:
                with pytest.raises(exception_type) as e:
                    check_email_annual_limit(service, notifications_requested)
                assert e.value.status_code == 429
                assert e.value.message == f"Exceeded annual email sending limit of {service.email_annual_limit} messages"
                assert log_msg in mock_logger.call_args[0][0]
            else:
                assert check_email_annual_limit(service, notifications_requested) is None
                if (not has_sent_reached_limit_email and is_reached) or (not has_sent_near_limit_email and is_near):
                    mock_redis_set.assert_called_with(service.id)
                    if log_msg:
                        assert log_msg in mock_logger.call_args[0][0]

    @freeze_time("2024-11-26")
    @pytest.mark.parametrize(
        "annual_limit, counts_from_redis, do_ft_insert, ft_count, notifications_requested, will_raise, has_sent_reached_limit_email, has_sent_near_limit_email, log_msg",
        [
            (100, 81, False, 0, 20, True, False, True, "is exceeding their annual SMS limit"),
            (100, 0, True, 100, 5, True, False, True, "is exceeding their annual SMS limit"),
            (100, 50, True, 50, 1, True, False, True, "is exceeding their annual SMS limit"),
            (100, 5, True, 50, 5, False, False, False, None),
            (100, 50, True, 29, 5, False, False, True, "reached 80% of their annual SMS limit of"),
            (100, 5, True, 50, 5, False, True, False, "reached their annual SMS limit of"),
        ],
        ids=[
            " Cache only - Service attempts to go over annual limit",
            " DB only - Service exceeded annual limit - attempts more sends",
            " Cache & DB - Service attempts to go over annual limit",
            " Cache only - Within annual limit - not near or over limit",
            " DB only - Within annual limit - near limit",
            " Cache & DB - Within annual limit - reaches limit with current send",
        ],
    )
    @pytest.mark.parametrize(
        "is_trial_service, exception_type",
        [(True, TrialServiceRequestExceedsSMSAnnualLimitError), (False, LiveServiceRequestExceedsSMSAnnualLimitError)],
        ids=["Trial service ", "Live service "],
    )
    def test_check_sms_annual_limit(
        self,
        notify_api,
        notify_db,
        notify_db_session,
        annual_limit,
        counts_from_redis,
        do_ft_insert,
        ft_count,
        is_trial_service,
        exception_type,
        notifications_requested,
        will_raise,
        has_sent_reached_limit_email,
        has_sent_near_limit_email,
        log_msg,
        mocker,
    ):
        mock_logger = mocker.patch("app.notifications.validators.current_app.logger.info")
        mock_redis_set = mocker.patch("app.redis_store.set_hash_value")  # Set over / near limit keys
        mocker.patch("app.redis_store.get", return_value=counts_from_redis)  # notifications fetched from Redis
        mocker.patch("app.annual_limit_client.check_has_warning_been_sent", return_value=has_sent_near_limit_email)
        mocker.patch(
            "app.annual_limit_client.check_has_warning_been_sent", return_value=has_sent_reached_limit_email
        )  # Email sent flag checks
        mocker.patch("app.notifications.validators.send_notification_to_service_users")
        is_near = (counts_from_redis + ft_count + notifications_requested) >= (annual_limit * 0.8)
        is_reached = (counts_from_redis + ft_count + notifications_requested) == annual_limit

        service = create_sample_service(notify_db, notify_db_session, restricted=is_trial_service, sms_annual_limit=annual_limit)
        email_template = create_sample_template(notify_db, notify_db_session, template_type=EMAIL_TYPE)
        sms_template = create_sample_template(notify_db, notify_db_session, template_type=SMS_TYPE)

        if do_ft_insert:
            # Previous fiscal year
            create_ft_notification_status(
                utc_date="2024-03-31",
                service=service,
                template=sms_template,
                notification_type=SMS_TYPE,
            )
            # Within current fiscal year
            create_ft_notification_status(
                utc_date="2024-04-01", service=service, template=sms_template, notification_type=SMS_TYPE, count=ft_count
            )
            # In the next fiscal year
            create_ft_notification_status(
                utc_date="2025-04-01", service=service, template=sms_template, notification_type=SMS_TYPE
            )
            # Make sure we're not counting non-email notifications
            create_ft_notification_status(
                utc_date="2024-04-01", service=service, template=email_template, notification_type=EMAIL_TYPE
            )

        with set_config(notify_api, "FF_ANNUAL_LIMIT", True):
            if will_raise:
                with pytest.raises(exception_type) as e:
                    check_sms_annual_limit(service, notifications_requested)
                assert e.value.status_code == 429
                assert e.value.message == f"Exceeded annual SMS sending limit of {service.sms_annual_limit} messages"
                assert log_msg in mock_logger.call_args[0][0]
            else:
                assert check_sms_annual_limit(service, notifications_requested) is None
                if (not has_sent_reached_limit_email and is_reached) or (not has_sent_near_limit_email and is_near):
                    mock_redis_set.assert_called_with(service.id)
                    if log_msg:
                        assert log_msg in mock_logger.call_args[0][0]

    def test_check_sms_annual_limit_only_sends_warning_email_once(
        self,
        notify_api,
        notify_db,
        notify_db_session,
        mocker,
    ):
        mocker.patch("app.redis_store.set_hash_value")
        mocker.patch("app.redis_store.get", return_value=45)
        mocker.patch("app.annual_limit_client.check_has_warning_been_sent", return_value=True)
        mock_send_email = mocker.patch("app.notifications.validators.send_notification_to_service_users")

        service = create_sample_service(notify_db, notify_db_session, sms_annual_limit=49)

        with set_config(notify_api, "FF_ANNUAL_LIMIT", True):
            check_sms_annual_limit(service, 2)
            mock_send_email.assert_not_called()

    def test_check_sms_annual_limit_only_sends_reached_limit_email_once(
        self,
        notify_api,
        notify_db,
        notify_db_session,
        mocker,
    ):
        mocker.patch("app.redis_store.set_hash_value")
        mocker.patch("app.redis_store.get", return_value=45)
        mocker.patch("app.annual_limit_client.check_has_over_limit_been_sent", return_value=True)
        mocker.patch("app.annual_limit_client.check_has_warning_been_sent", return_value=True)
        mock_send_email = mocker.patch("app.notifications.validators.send_notification_to_service_users")

        service = create_sample_service(notify_db, notify_db_session, sms_annual_limit=49)

        with set_config(notify_api, "FF_ANNUAL_LIMIT", True):
            check_sms_annual_limit(service, 4)
            mock_send_email.assert_not_called()
