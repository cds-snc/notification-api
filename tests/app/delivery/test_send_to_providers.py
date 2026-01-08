import uuid
from collections import namedtuple
from datetime import datetime
from unittest import TestCase
from unittest.mock import ANY, MagicMock, call

import pytest
from flask import current_app
from notifications_utils.recipients import validate_and_format_phone_number
from pytest_mock import MockFixture

import app
from app import aws_sns_client
from app.config import Config
from app.dao import notifications_dao, provider_details_dao
from app.dao.provider_details_dao import (
    dao_switch_sms_provider_to_provider_with_identifier,
)
from app.delivery import send_to_providers
from app.exceptions import (
    DocumentDownloadException,
    InvalidUrlException,
    MalwareDetectedException,
    MalwareScanInProgressException,
    NotificationTechnicalFailureException,
)
from app.models import (
    BRANDING_BOTH_EN,
    BRANDING_BOTH_FR,
    BRANDING_ORG_BANNER_NEW,
    BRANDING_ORG_NEW,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    BounceRateStatus,
    EmailBranding,
    Notification,
    Service,
)
from tests.app.conftest import create_sample_email_template, document_download_response
from tests.app.db import (
    create_notification,
    create_reply_to_email,
    create_service,
    create_service_sms_sender,
    create_service_with_defined_sms_sender,
    create_template,
    save_notification,
)
from tests.conftest import set_config_values


class TestProviderToUse:
    def test_should_use_pinpoint_for_sms_by_default_if_configured(self, restore_provider_details, notify_api):
        with set_config_values(
            notify_api,
            {
                "AWS_PINPOINT_SC_POOL_ID": "sc_pool_id",
                "AWS_PINPOINT_DEFAULT_POOL_ID": "default_pool_id",
            },
        ):
            provider = send_to_providers.provider_to_use("sms", "1234", "+16135551234")
        assert provider.name == "pinpoint"

    def test_should_use_sns_for_sms_by_default_if_partially_configured(self, restore_provider_details, notify_api):
        with set_config_values(
            notify_api,
            {
                "AWS_PINPOINT_SC_POOL_ID": "sc_pool_id",
                "AWS_PINPOINT_DEFAULT_POOL_ID": "",
                "AWS_PINPOINT_SC_TEMPLATE_IDS": [],
            },
        ):
            provider = send_to_providers.provider_to_use("sms", "1234", "+16135551234", template_id=uuid.uuid4())
        assert provider.name == "sns"

    def test_should_use_pinpoint_for_sms_for_sc_template_if_sc_pool_configured(self, restore_provider_details, notify_api):
        sc_template = uuid.uuid4()
        with set_config_values(
            notify_api,
            {
                "AWS_PINPOINT_SC_POOL_ID": "sc_pool_id",
                "AWS_PINPOINT_DEFAULT_POOL_ID": "",
                "AWS_PINPOINT_SC_TEMPLATE_IDS": [str(sc_template)],
            },
        ):
            provider = send_to_providers.provider_to_use("sms", "1234", "+16135551234", template_id=sc_template)
        assert provider.name == "pinpoint"

    def test_should_use_sns_for_sms_if_dedicated_number(self, restore_provider_details, notify_api):
        with set_config_values(
            notify_api,
            {
                "AWS_PINPOINT_SC_POOL_ID": "sc_pool_id",
                "AWS_PINPOINT_DEFAULT_POOL_ID": "default_pool_id",
            },
        ):
            provider = send_to_providers.provider_to_use("sms", "1234", "+16135551234", False, "+12345678901")
        assert provider.name == "sns"

    def test_should_use_sns_for_sms_if_sending_to_the_US(self, restore_provider_details, notify_api):
        with set_config_values(
            notify_api,
            {
                "AWS_PINPOINT_SC_POOL_ID": "sc_pool_id",
                "AWS_PINPOINT_DEFAULT_POOL_ID": "default_pool_id",
            },
        ):
            provider = send_to_providers.provider_to_use("sms", "1234", "+17065551234")
        assert provider.name == "sns"

    @pytest.mark.serial
    def test_should_use_pinpoint_for_sms_if_sending_outside_zone_1(self, restore_provider_details, notify_api):
        with set_config_values(
            notify_api,
            {
                "AWS_PINPOINT_SC_POOL_ID": "sc_pool_id",
                "AWS_PINPOINT_DEFAULT_POOL_ID": "default_pool_id",
            },
        ):
            provider = send_to_providers.provider_to_use("sms", "1234", "+447512501324", international=True)
        assert provider.name == "pinpoint"

    def test_should_use_sns_for_sms_if_sending_to_non_CA_zone_1(self, restore_provider_details, notify_api):
        with set_config_values(
            notify_api,
            {
                "AWS_PINPOINT_SC_POOL_ID": "sc_pool_id",
                "AWS_PINPOINT_DEFAULT_POOL_ID": "default_pool_id",
            },
        ):
            provider = send_to_providers.provider_to_use("sms", "1234", "+16715550123")
        assert provider.name == "sns"

    def test_should_use_sns_for_sms_if_match_fails(self, restore_provider_details, notify_api):
        with set_config_values(
            notify_api,
            {
                "AWS_PINPOINT_SC_POOL_ID": "sc_pool_id",
                "AWS_PINPOINT_DEFAULT_POOL_ID": "default_pool_id",
            },
        ):
            provider = send_to_providers.provider_to_use("sms", "1234", "8695550123")  # This number fails our matching code
        assert provider.name == "sns"

    @pytest.mark.parametrize("sc_pool_id, default_pool_id", [("", "default_pool_id"), ("sc_pool_id", "")])
    def test_should_use_sns_if_pinpoint_not_configured(self, restore_provider_details, notify_api, sc_pool_id, default_pool_id):
        with set_config_values(
            notify_api,
            {
                "AWS_PINPOINT_SC_POOL_ID": sc_pool_id,
                "AWS_PINPOINT_DEFAULT_POOL_ID": default_pool_id,
            },
        ):
            provider = send_to_providers.provider_to_use("sms", "1234", "+16135551234")
        assert provider.name == "sns"


@pytest.mark.skip(reason="Currently using only 1 SMS provider")
def test_should_return_highest_priority_active_provider(restore_provider_details):
    providers = provider_details_dao.get_provider_details_by_notification_type("sms")
    providers = [provider for provider in providers if provider.active]

    first = providers[0]
    second = providers[1]

    assert send_to_providers.provider_to_use("sms", "1234").name == first.identifier

    first.priority = 12
    second.priority = 10

    provider_details_dao.dao_update_provider_details(first)
    provider_details_dao.dao_update_provider_details(second)

    assert send_to_providers.provider_to_use("sms", "1234").name == second.identifier

    first.priority = 10
    first.active = False
    second.priority = 12

    provider_details_dao.dao_update_provider_details(first)
    provider_details_dao.dao_update_provider_details(second)

    assert send_to_providers.provider_to_use("sms", "1234").name == second.identifier

    first.active = True
    provider_details_dao.dao_update_provider_details(first)

    assert send_to_providers.provider_to_use("sms", "1234").name == first.identifier


def test_should_handle_opted_out_phone_numbers_if_using_pinpoint(notify_api, sample_template, mocker):
    mocker.patch("app.aws_pinpoint_client.send_sms", return_value="opted_out")
    db_notification = save_notification(
        create_notification(
            template=sample_template,
            to_field="+16135551234",
            status="created",
            reply_to_text=sample_template.service.get_default_sms_sender(),
        )
    )

    with set_config_values(
        notify_api,
        {
            "AWS_PINPOINT_SC_POOL_ID": "sc_pool_id",
            "AWS_PINPOINT_DEFAULT_POOL_ID": "default_pool_id",
        },
    ):
        send_to_providers.send_sms_to_provider(db_notification)

        notification = Notification.query.filter_by(id=db_notification.id).one()
        assert notification.status == "permanent-failure"
        assert notification.provider_response == "Phone number is opted out"


def test_should_send_personalised_template_to_correct_sms_provider_and_persist(sample_sms_template_with_html, mocker):
    db_notification = save_notification(
        create_notification(
            template=sample_sms_template_with_html,
            to_field="+16502532222",
            personalisation={"name": "Jo"},
            status="created",
            reply_to_text=sample_sms_template_with_html.service.get_default_sms_sender(),
        )
    )

    statsd_mock = mocker.patch("app.delivery.send_to_providers.statsd_client")
    mocker.patch("app.aws_sns_client.send_sms", return_value="message_id_from_sns")

    send_to_providers.send_sms_to_provider(db_notification)

    aws_sns_client.send_sms.assert_called_once_with(
        to=validate_and_format_phone_number("+16502532222"),
        content="Sample service: Hello Jo\nHere is <em>some HTML</em> & entities",
        reference=str(db_notification.id),
        sender=current_app.config["FROM_NUMBER"],
        template_id=sample_sms_template_with_html.id,
        service_id=sample_sms_template_with_html.service_id,
        sending_vehicle=None,
    )

    notification = Notification.query.filter_by(id=db_notification.id).one()

    assert notification.status == "sent"
    assert notification.sent_at <= datetime.utcnow()
    assert notification.sent_by == "sns"
    assert notification.billable_units == 1
    assert notification.personalisation == {"name": "Jo"}
    assert notification.reference == "message_id_from_sns"

    statsd_timing_calls = statsd_mock.timing_with_dates.call_args_list

    assert call("sms.total-time", notification.sent_at, notification.created_at) in statsd_timing_calls
    assert call("sms.process_type-normal", notification.sent_at, notification.created_at) in statsd_timing_calls
    assert call("sms.process_type-normal") in statsd_mock.incr.call_args_list


def test_should_send_personalised_template_to_correct_email_provider_and_persist(sample_email_template_with_html, mocker):
    db_notification = save_notification(
        create_notification(
            template=sample_email_template_with_html,
            to_field="jo.smith@example.com",
            personalisation={"name": "Jo"},
        )
    )

    mocker.patch("app.aws_ses_client.send_email", return_value="reference")
    statsd_mock = mocker.patch("app.delivery.send_to_providers.statsd_client")
    mocker.patch("app.delivery.send_to_providers.bounce_rate_client")

    send_to_providers.send_email_to_provider(db_notification)

    app.aws_ses_client.send_email.assert_called_once_with(
        '"=?utf-8?B?U2FtcGxlIHNlcnZpY2U=?=" <sample.service@notification.canada.ca>',
        "jo.smith@example.com",
        "Jo <em>some HTML</em>",
        body="Hello Jo\nThis is an email from GOV.\u200bUK with <em>some HTML</em>\n",
        html_body=ANY,
        reply_to_address=None,
        attachments=[],
    )

    assert "<!DOCTYPE html" in app.aws_ses_client.send_email.call_args[1]["html_body"]
    assert "&lt;em&gt;some HTML&lt;/em&gt;" in app.aws_ses_client.send_email.call_args[1]["html_body"]

    notification = Notification.query.filter_by(id=db_notification.id).one()
    assert notification.status == "sending"
    assert notification.sent_at <= datetime.utcnow()
    assert notification.sent_by == "ses"
    assert notification.personalisation == {"name": "Jo"}

    statsd_timing_calls = statsd_mock.timing_with_dates.call_args_list
    statsd_key = "email.no-attachments.process_type-normal"
    assert call("email.total-time", notification.sent_at, notification.created_at) in statsd_timing_calls
    assert call(statsd_key, notification.sent_at, notification.created_at) in statsd_timing_calls
    assert call(statsd_key) in statsd_mock.incr.call_args_list


@pytest.mark.skip(reason="the validator can throw a 500 causing us to fail all tests")
def test_should_send_personalised_template_with_html_enabled(sample_email_template_with_advanced_html, mocker, notify_api):
    db_notification = save_notification(
        create_notification(
            template=sample_email_template_with_advanced_html,
            to_field="jo.smith@example.com",
            personalisation={"name": "Jo"},
        )
    )

    mocker.patch("app.aws_ses_client.send_email", return_value="reference")

    with set_config_values(
        notify_api,
        {
            "ALLOW_HTML_SERVICE_IDS": str(db_notification.service.id),
        },
    ):
        send_to_providers.send_email_to_provider(db_notification)

    app.aws_ses_client.send_email.assert_called_once_with(
        '"Sample service" <sample.service@notification.canada.ca>',
        "jo.smith@example.com",
        "Jo <em>some HTML</em>",
        body="<div style='color: pink' dir='rtl'>Jo <em>some HTML</em> that should be right aligned</div>\n",
        html_body=ANY,
        reply_to_address=None,
        attachments=[],
    )

    assert "<!DOCTYPE html" in app.aws_ses_client.send_email.call_args[1]["html_body"]
    assert (
        "<div style='color: pink' dir='rtl'>Jo <em>some HTML</em> that should be right aligned</div>"
        in app.aws_ses_client.send_email.call_args[1]["html_body"]
    )


def test_should_not_send_email_message_when_service_is_inactive_notifcation_is_in_tech_failure(
    sample_service, sample_notification, mocker
):
    sample_service.active = False
    send_mock = mocker.patch("app.aws_ses_client.send_email", return_value="reference")

    with pytest.raises(NotificationTechnicalFailureException) as e:
        send_to_providers.send_email_to_provider(sample_notification)
    assert str(sample_notification.id) in str(e.value)
    send_mock.assert_not_called()
    assert Notification.query.get(sample_notification.id).status == "technical-failure"


def test_should_respect_custom_sending_domains(sample_service, mocker, sample_email_template_with_html):
    db_notification = save_notification(
        create_notification(
            template=sample_email_template_with_html,
            to_field="jo.smith@example.com",
            personalisation={"name": "Jo"},
        )
    )

    sample_service.sending_domain = "foo.bar"
    mocker.patch("app.aws_ses_client.send_email", return_value="reference")
    mocker.patch("app.delivery.send_to_providers.bounce_rate_client")

    send_to_providers.send_email_to_provider(db_notification)

    app.aws_ses_client.send_email.assert_called_once_with(
        '"=?utf-8?B?U2FtcGxlIHNlcnZpY2U=?=" <sample.service@foo.bar>',
        "jo.smith@example.com",
        "Jo <em>some HTML</em>",
        body="Hello Jo\nThis is an email from GOV.\u200bUK with <em>some HTML</em>\n",
        html_body=ANY,
        reply_to_address=None,
        attachments=[],
    )


@pytest.mark.parametrize("client_send", ["app.aws_sns_client.send_sms"])
def test_should_not_send_sms_message_when_service_is_inactive_notifcation_is_in_tech_failure(
    sample_service, sample_notification, mocker, client_send
):
    sample_service.active = False
    send_mock = mocker.patch(client_send, return_value="reference")

    with pytest.raises(NotificationTechnicalFailureException) as e:
        send_to_providers.send_sms_to_provider(sample_notification)
    assert str(sample_notification.id) in str(e.value)
    send_mock.assert_not_called()
    assert Notification.query.get(sample_notification.id).status == "technical-failure"


@pytest.mark.parametrize("var", ["", " "])
def test_should_not_send_sms_message_when_message_is_empty_or_whitespace(sample_service, mocker, var):
    sample_service.prefix_sms = False
    template = create_template(sample_service, content="((var))")
    notification = save_notification(
        create_notification(
            template=template,
            personalisation={"var": var},
            to_field="+16502532222",
            status="created",
            reply_to_text=sample_service.get_default_sms_sender(),
        )
    )

    send_mock = mocker.patch("app.aws_sns_client.send_sms", return_value="reference")

    send_to_providers.send_sms_to_provider(notification)

    send_mock.assert_not_called()
    assert Notification.query.get(notification.id).status == "technical-failure"


def test_should_not_send_sms_message_to_internal_test_number(sample_service, mocker):
    template = create_template(sample_service)
    notification = save_notification(
        create_notification(
            template=template,
            to_field=Config.INTERNAL_TEST_NUMBER,
            status="created",
            reply_to_text=sample_service.get_default_sms_sender(),
        )
    )
    mocker.patch("app.delivery.send_to_providers.send_sms_response", return_value="reference")
    send_mock = mocker.patch("app.aws_sns_client.send_sms")
    send_to_providers.send_sms_to_provider(notification)

    send_mock.assert_not_called()
    assert Notification.query.get(notification.id).status == "sent"


def test_send_sms_should_use_template_version_from_notification_not_latest(sample_template, mocker):
    db_notification = save_notification(
        create_notification(
            template=sample_template,
            to_field="+16502532222",
            status="created",
            reply_to_text=sample_template.service.get_default_sms_sender(),
        )
    )

    mocker.patch("app.aws_sns_client.send_sms", return_value="message_id_from_sns")

    version_on_notification = sample_template.version

    # Change the template
    from app.dao.templates_dao import dao_get_template_by_id, dao_update_template

    sample_template.content = sample_template.content + " another version of the template"
    dao_update_template(sample_template)
    t = dao_get_template_by_id(sample_template.id)
    assert t.version > version_on_notification

    send_to_providers.send_sms_to_provider(db_notification)

    aws_sns_client.send_sms.assert_called_once_with(
        to=validate_and_format_phone_number("+16502532222"),
        content="Sample service: This is a template:\nwith a newline",
        reference=str(db_notification.id),
        sender=current_app.config["FROM_NUMBER"],
        template_id=sample_template.id,
        service_id=sample_template.service_id,
        sending_vehicle=ANY,
    )

    persisted_notification = notifications_dao.get_notification_by_id(db_notification.id)
    assert persisted_notification.to == db_notification.to
    assert persisted_notification.template_id == sample_template.id
    assert persisted_notification.template_version == version_on_notification
    assert persisted_notification.template_version != sample_template.version
    assert persisted_notification.status == "sent"
    assert persisted_notification.reference == "message_id_from_sns"
    assert not persisted_notification.personalisation


def test_send_sms_falls_back_to_current_template_category_for_old_template_versions(sample_template, mocker, notify_db_session):
    """
    Test that when an old template version (from templates_history) doesn't have template_category_id in __dict__,
    the code falls back to the current template's template_category_id to determine sending_vehicle.
    This handles templates created before migration 0454 (June 2024) when template_category_id
    was added to templates_history.
    """
    from app.clients.sms import SmsSendingVehicles
    from app.dao.template_categories_dao import dao_create_template_category
    from app.dao.templates_dao import dao_get_template_by_id, dao_update_template
    from app.models import TemplateCategory

    # Create a template category with short_code
    category = TemplateCategory(
        name_en="Authentication",
        name_fr="Authentification",
        sms_process_type="priority",
        email_process_type="priority",
        hidden=False,
        sms_sending_vehicle="short_code",
        created_by_id=sample_template.created_by_id,
    )
    dao_create_template_category(category)

    # Update the sample template to use this category
    sample_template.template_category_id = category.id
    dao_update_template(sample_template)

    # Create a notification
    notification = save_notification(
        create_notification(
            template=sample_template,
            to_field="+16502532222",
            status="created",
            reply_to_text=sample_template.service.get_default_sms_sender(),
        )
    )

    # Mock dao_get_template_by_id to simulate an old template history without template_category_id in __dict__
    # First call returns template history without category_id (simulating old data)
    # Second call returns current template with category_id (fallback)
    class MockTemplateHistory:
        def __init__(self):
            self.id = sample_template.id
            self.version = sample_template.version
            self.content = sample_template.content
            self.template_type = sample_template.template_type
            self.process_type = sample_template.process_type
            # Simulate old template history: __dict__ doesn't have template_category_id
            # This is what happens with templates created before migration 0454
            self.__dict__ = {
                "id": self.id,
                "content": self.content,
                "template_type": self.template_type,
                "process_type": self.process_type,
                # Note: template_category_id is intentionally missing
            }

    mock_history = MockTemplateHistory()
    current_template = dao_get_template_by_id(sample_template.id)

    mock_get_template = mocker.patch(
        "app.delivery.send_to_providers.dao_get_template_by_id",
        side_effect=[mock_history, current_template],
    )

    # Mock the SMS provider
    mocker.patch("app.aws_pinpoint_client.send_sms", return_value="message_id")

    # Execute
    send_to_providers.send_sms_to_provider(notification)

    # Verify the fallback happened: dao_get_template_by_id should be called twice
    assert mock_get_template.call_count == 2
    # First call with version number (gets old history)
    mock_get_template.assert_any_call(sample_template.id, notification.template_version)
    # Second call without version (gets current template for fallback)
    mock_get_template.assert_any_call(sample_template.id)

    # Verify the SMS was sent with the correct sending_vehicle (short_code)
    app.aws_pinpoint_client.send_sms.assert_called_once()
    call_kwargs = app.aws_pinpoint_client.send_sms.call_args[1]
    assert call_kwargs["sending_vehicle"] == SmsSendingVehicles.SHORT_CODE


@pytest.mark.parametrize("research_mode, key_type", [(True, KEY_TYPE_NORMAL), (False, KEY_TYPE_TEST)])
def test_should_call_send_sms_response_task_if_research_mode(
    notify_db, sample_service, sample_notification, mocker, research_mode, key_type
):
    mocker.patch("app.aws_sns_client.send_sms")
    mocker.patch("app.delivery.send_to_providers.send_sms_response", return_value="not-used")

    if research_mode:
        sample_service.research_mode = True
        notify_db.session.add(sample_service)
        notify_db.session.commit()

    sample_notification.key_type = key_type

    send_to_providers.send_sms_to_provider(sample_notification)
    assert not aws_sns_client.send_sms.called

    app.delivery.send_to_providers.send_sms_response.assert_called_once_with(
        "sns", sample_notification.to, sample_notification.reference
    )

    persisted_notification = notifications_dao.get_notification_by_id(sample_notification.id)
    assert persisted_notification.to == sample_notification.to
    assert persisted_notification.template_id == sample_notification.template_id
    assert persisted_notification.status == "sent"
    assert persisted_notification.sent_at <= datetime.utcnow()
    assert persisted_notification.sent_by == "sns"
    assert not persisted_notification.personalisation


def test_should_not_send_to_provider_when_status_is_not_created(sample_template, mocker):
    notification = save_notification(create_notification(template=sample_template, status="sending"))
    mocker.patch("app.aws_sns_client.send_sms")
    response_mock = mocker.patch("app.delivery.send_to_providers.send_sms_response")

    send_to_providers.send_sms_to_provider(notification)

    app.aws_sns_client.send_sms.assert_not_called()
    response_mock.assert_not_called()


def test_should_send_sms_with_downgraded_content(notify_db_session, mocker):
    # é, o, and u are in GSM.
    # grapes, tabs, zero width space and ellipsis are not
    msg = "é o u 🍇 foo\tbar\u200bbaz((misc))…"
    placeholder = "∆∆∆abc"
    gsm_message = "?odz Housing Service: é o u ? foo barbaz???abc..."
    service = create_service(service_name="Łódź Housing Service")
    template = create_template(service, content=msg)
    db_notification = save_notification(create_notification(template=template, personalisation={"misc": placeholder}))

    mocker.patch("app.aws_sns_client.send_sms", return_value="message_id_from_sns")

    send_to_providers.send_sms_to_provider(db_notification)

    aws_sns_client.send_sms.assert_called_once_with(
        to=ANY, content=gsm_message, reference=ANY, sender=ANY, template_id=ANY, service_id=ANY, sending_vehicle=ANY
    )


def test_send_sms_should_use_service_sms_sender(sample_service, sample_template, mocker):
    mocker.patch("app.aws_sns_client.send_sms", return_value="message_id_from_sns")

    sms_sender = create_service_sms_sender(service=sample_service, sms_sender="123456", is_default=False)
    db_notification = save_notification(create_notification(template=sample_template, reply_to_text=sms_sender.sms_sender))

    send_to_providers.send_sms_to_provider(
        db_notification,
    )

    app.aws_sns_client.send_sms.assert_called_once_with(
        to=ANY,
        content=ANY,
        reference=ANY,
        sender=sms_sender.sms_sender,
        template_id=ANY,
        service_id=ANY,
        sending_vehicle=ANY,
    )


@pytest.mark.parametrize("research_mode,key_type", [(True, KEY_TYPE_NORMAL), (False, KEY_TYPE_TEST)])
def test_send_email_to_provider_should_call_research_mode_task_response_task_if_research_mode(
    sample_service, sample_email_template, mocker, research_mode, key_type
):
    notification = save_notification(
        create_notification(
            template=sample_email_template,
            to_field="john@smith.com",
            key_type=key_type,
            billable_units=0,
        )
    )
    sample_service.research_mode = research_mode

    reference = str(uuid.uuid4())
    mocker.patch("app.aws_ses_client.send_email")
    mocker.patch("app.delivery.send_to_providers.send_email_response", return_value=reference)

    send_to_providers.send_email_to_provider(notification)

    assert not app.aws_ses_client.send_email.called
    app.delivery.send_to_providers.send_email_response.assert_called_once_with("john@smith.com")
    persisted_notification = Notification.query.filter_by(id=notification.id).one()
    assert persisted_notification.to == "john@smith.com"
    assert persisted_notification.template_id == sample_email_template.id
    assert persisted_notification.status == "sending"
    assert persisted_notification.sent_at <= datetime.utcnow()
    assert persisted_notification.created_at <= datetime.utcnow()
    assert persisted_notification.sent_by == "ses"
    assert persisted_notification.reference == str(reference)
    assert persisted_notification.billable_units == 0


def test_send_email_to_provider_should_not_send_to_provider_when_status_is_not_created(sample_email_template, mocker):
    notification = save_notification(create_notification(template=sample_email_template, status="sending"))
    mocker.patch("app.aws_ses_client.send_email")
    mocker.patch("app.delivery.send_to_providers.send_email_response")

    send_to_providers.send_email_to_provider(notification)
    app.aws_ses_client.send_email.assert_not_called()
    app.delivery.send_to_providers.send_email_response.assert_not_called()


def test_send_email_should_use_service_reply_to_email(sample_service, sample_email_template, mocker):
    mocker.patch("app.aws_ses_client.send_email", return_value="reference")
    mocker.patch("app.delivery.send_to_providers.bounce_rate_client")

    db_notification = save_notification(create_notification(template=sample_email_template, reply_to_text="foo@bar.com"))
    create_reply_to_email(service=sample_service, email_address="foo@bar.com")

    send_to_providers.send_email_to_provider(
        db_notification,
    )

    app.aws_ses_client.send_email.assert_called_once_with(
        ANY,
        ANY,
        ANY,
        body=ANY,
        html_body=ANY,
        reply_to_address="foo@bar.com",
        attachments=[],
    )


def test_send_email_should_use_default_service_reply_to_email_when_two_are_set(sample_service, sample_email_template, mocker):
    mocker.patch("app.aws_ses_client.send_email", return_value="reference")
    mocker.patch("app.delivery.send_to_providers.bounce_rate_client")

    create_reply_to_email(service=sample_service, email_address="foo@bar.com")
    create_reply_to_email(service=sample_service, email_address="foo_two@bar.com", is_default=False)

    db_notification = save_notification(create_notification(template=sample_email_template, reply_to_text="foo@bar.com"))

    send_to_providers.send_email_to_provider(
        db_notification,
    )

    app.aws_ses_client.send_email.assert_called_once_with(
        ANY,
        ANY,
        ANY,
        body=ANY,
        html_body=ANY,
        reply_to_address="foo@bar.com",
        attachments=[],
    )


def test_send_email_should_use_non_default_service_reply_to_email_when_it_is_set(sample_service, sample_email_template, mocker):
    mocker.patch("app.aws_ses_client.send_email", return_value="reference")
    mocker.patch("app.delivery.send_to_providers.bounce_rate_client")

    create_reply_to_email(service=sample_service, email_address="foo@bar.com")
    create_reply_to_email(service=sample_service, email_address="foo_two@bar.com", is_default=False)

    db_notification = save_notification(create_notification(template=sample_email_template, reply_to_text="foo_two@bar.com"))

    send_to_providers.send_email_to_provider(
        db_notification,
    )

    app.aws_ses_client.send_email.assert_called_once_with(
        ANY,
        ANY,
        ANY,
        body=ANY,
        html_body=ANY,
        reply_to_address="foo_two@bar.com",
        attachments=[],
    )


def test_get_html_email_renderer_should_return_for_normal_service(sample_service):
    options = send_to_providers.get_html_email_options(sample_service)
    assert options["fip_banner_english"] is True
    assert options["fip_banner_french"] is False
    assert "brand_colour" not in options.keys()
    assert "brand_logo" not in options.keys()
    assert "brand_text" not in options.keys()
    assert "brand_name" not in options.keys()


@pytest.mark.parametrize(
    "branding_type, fip_banner_english, fip_banner_french",
    [
        (BRANDING_ORG_NEW, False, False),
        (BRANDING_BOTH_EN, True, False),
        (BRANDING_BOTH_FR, False, True),
        (BRANDING_ORG_BANNER_NEW, False, False),
    ],
)
def test_get_html_email_renderer_with_branding_details(
    branding_type, fip_banner_english, fip_banner_french, notify_db, sample_service
):
    email_branding = EmailBranding(
        brand_type=branding_type,
        colour="#000000",
        logo="justice-league.png",
        name="Justice League",
        text="League of Justice",
        created_by_id=sample_service.created_by.id,
    )
    sample_service.email_branding = email_branding
    notify_db.session.add_all([sample_service, email_branding])
    notify_db.session.commit()

    options = send_to_providers.get_html_email_options(sample_service)

    assert options["fip_banner_english"] == fip_banner_english
    assert options["fip_banner_french"] == fip_banner_french
    assert options["brand_colour"] == "#000000"
    assert options["brand_text"] == "League of Justice"
    assert options["brand_name"] == "Justice League"

    if branding_type == BRANDING_ORG_BANNER_NEW:
        assert options["logo_with_background_colour"] is True
    else:
        assert options["logo_with_background_colour"] is False


def test_get_html_email_renderer_with_branding_details_and_render_fip_banner_english_only(notify_db, sample_service):
    sample_service.email_branding = None
    notify_db.session.add_all([sample_service])
    notify_db.session.commit()
    options = send_to_providers.get_html_email_options(sample_service)

    assert options == {
        "fip_banner_english": True,
        "fip_banner_french": False,
        "logo_with_background_colour": False,
        "alt_text_en": None,
        "alt_text_fr": None,
    }


def test_get_html_email_renderer_prepends_logo_path(notify_api):
    Service = namedtuple("Service", ["email_branding"])
    EmailBranding = namedtuple("EmailBranding", ["brand_type", "colour", "name", "logo", "text", "alt_text_en", "alt_text_fr"])

    email_branding = EmailBranding(
        brand_type=BRANDING_ORG_NEW,
        colour="#000000",
        logo="justice-league.png",
        name="Justice League",
        text="League of Justice",
        alt_text_en="alt_text_en",
        alt_text_fr="alt_text_fr",
    )
    service = Service(
        email_branding=email_branding,
    )

    renderer = send_to_providers.get_html_email_options(service)
    domain = "https://assets.notification.canada.ca"
    assert renderer["brand_logo"] == "{}{}".format(domain, "/justice-league.png")


def test_get_html_email_renderer_handles_email_branding_without_logo(notify_api):
    Service = namedtuple("Service", ["email_branding"])
    EmailBranding = namedtuple("EmailBranding", ["brand_type", "colour", "name", "logo", "text", "alt_text_en", "alt_text_fr"])

    email_branding = EmailBranding(
        brand_type=BRANDING_ORG_BANNER_NEW,
        colour="#000000",
        logo=None,
        name="Justice League",
        text="League of Justice",
        alt_text_en="alt_text_en",
        alt_text_fr="alt_text_fr",
    )
    service = Service(
        email_branding=email_branding,
    )

    renderer = send_to_providers.get_html_email_options(service)

    assert renderer["fip_banner_english"] is False
    assert renderer["logo_with_background_colour"] is True
    assert renderer["brand_logo"] is None
    assert renderer["brand_text"] == "League of Justice"
    assert renderer["brand_colour"] == "#000000"
    assert renderer["brand_name"] == "Justice League"
    assert renderer["alt_text_en"] == "alt_text_en"
    assert renderer["alt_text_fr"] == "alt_text_fr"


def test_should_not_update_notification_if_research_mode_on_exception(sample_service, sample_notification, mocker):
    mock_send_sms = mocker.patch("app.delivery.send_to_providers.send_sms_response", side_effect=Exception())
    sample_service.research_mode = True
    sample_notification.billable_units = 0

    with pytest.raises(Exception):
        send_to_providers.send_sms_to_provider(sample_notification)

    persisted_notification = notifications_dao.get_notification_by_id(sample_notification.id)
    assert persisted_notification.billable_units == 0
    assert mock_send_sms.called


def __update_notification(notification_to_update, research_mode, expected_status):
    if research_mode or notification_to_update.key_type == KEY_TYPE_TEST:
        notification_to_update.status = expected_status


@pytest.mark.parametrize(
    "research_mode,key_type, billable_units, expected_status",
    [
        (True, KEY_TYPE_NORMAL, 0, "delivered"),
        (False, KEY_TYPE_NORMAL, 1, "sent"),
        (False, KEY_TYPE_TEST, 0, "sent"),
        (True, KEY_TYPE_TEST, 0, "sent"),
        (True, KEY_TYPE_TEAM, 0, "delivered"),
        (False, KEY_TYPE_TEAM, 1, "sent"),
    ],
)
def test_should_update_billable_units_and_status_according_to_research_mode_and_key_type(
    sample_template, mocker, research_mode, key_type, billable_units, expected_status
):
    notification = save_notification(
        create_notification(template=sample_template, billable_units=0, status="created", key_type=key_type)
    )
    mocker.patch("app.aws_sns_client.send_sms", return_value="message_id_from_sns")
    mocker.patch(
        "app.delivery.send_to_providers.send_sms_response",
        side_effect=__update_notification(notification, research_mode, expected_status),
    )

    if research_mode:
        sample_template.service.research_mode = True

    send_to_providers.send_sms_to_provider(notification)
    assert notification.billable_units == billable_units
    assert notification.status == expected_status


def test_should_set_notification_billable_units_if_sending_to_provider_fails(
    sample_notification,
    mocker,
):
    mocker.patch("app.aws_sns_client.send_sms", side_effect=Exception())
    mock_toggle_provider = mocker.patch("app.delivery.send_to_providers.dao_toggle_sms_provider")

    sample_notification.billable_units = 0
    assert sample_notification.sent_by is None

    with pytest.raises(Exception):
        send_to_providers.send_sms_to_provider(sample_notification)

    assert sample_notification.billable_units == 1
    assert mock_toggle_provider.called


@pytest.mark.skip(reason="Currently not supporting international providers")
def test_should_send_sms_to_international_providers(restore_provider_details, sample_sms_template_with_html, sample_user, mocker):
    mocker.patch("app.provider_details.switch_providers.get_user_by_id", return_value=sample_user)

    dao_switch_sms_provider_to_provider_with_identifier("firetext")

    db_notification_uk = save_notification(
        create_notification(
            template=sample_sms_template_with_html,
            to_field="+16135555555",
            personalisation={"name": "Jo"},
            status="created",
            international=False,
            reply_to_text=sample_sms_template_with_html.service.get_default_sms_sender(),
        )
    )

    db_notification_international = save_notification(
        create_notification(
            template=sample_sms_template_with_html,
            to_field="+1613555555",
            personalisation={"name": "Jo"},
            status="created",
            international=False,
            reply_to_text=sample_sms_template_with_html.service.get_default_sms_sender(),
        )
    )

    mocker.patch("app.aws_sns_client.send_sms")

    send_to_providers.send_sms_to_provider(db_notification_uk)

    send_to_providers.send_sms_to_provider(db_notification_international)

    aws_sns_client.send_sms.assert_called_once_with(
        to="601117224412",
        content=ANY,
        reference=str(db_notification_international.id),
        sender=current_app.config["FROM_NUMBER"],
    )

    notification_uk = Notification.query.filter_by(id=db_notification_uk.id).one()
    notification_int = Notification.query.filter_by(id=db_notification_international.id).one()

    assert notification_uk.status == "sending"
    assert notification_uk.sent_by == "firetext"
    assert notification_int.status == "sent"


@pytest.mark.parametrize(
    "sms_sender, expected_sender, prefix_sms, expected_content",
    [
        ("foo", "foo", False, "bar"),
        ("foo", "foo", True, "Sample service: bar"),
        # if 40604 is actually in DB then treat that as if entered manually
        ("40604", "40604", False, "bar"),
        # 'testing' is the FROM_NUMBER during unit tests
        ("testing", "testing", True, "Sample service: bar"),
        ("testing", "testing", False, "bar"),
    ],
)
def test_should_handle_sms_sender_and_prefix_message(
    mocker, sms_sender, prefix_sms, expected_sender, expected_content, notify_db_session
):
    mocker.patch("app.aws_sns_client.send_sms", return_value="message_id_from_sns")
    service = create_service_with_defined_sms_sender(sms_sender_value=sms_sender, prefix_sms=prefix_sms)
    template = create_template(service, content="bar")
    notification = save_notification(create_notification(template, reply_to_text=sms_sender))

    send_to_providers.send_sms_to_provider(notification)

    aws_sns_client.send_sms.assert_called_once_with(
        content=expected_content,
        sender=expected_sender,
        to=ANY,
        reference=ANY,
        template_id=ANY,
        service_id=ANY,
        sending_vehicle=ANY,
    )


def test_send_email_to_provider_uses_reply_to_from_notification(sample_email_template, mocker):
    mocker.patch("app.aws_ses_client.send_email", return_value="reference")
    mocker.patch("app.delivery.send_to_providers.bounce_rate_client")

    db_notification = save_notification(create_notification(template=sample_email_template, reply_to_text="test@test.com"))

    send_to_providers.send_email_to_provider(
        db_notification,
    )

    app.aws_ses_client.send_email.assert_called_once_with(
        ANY,
        ANY,
        ANY,
        body=ANY,
        html_body=ANY,
        reply_to_address="test@test.com",
        attachments=[],
    )


def test_should_not_send_email_message_to_internal_test_address(sample_service, sample_email_template, mocker):
    notification = save_notification(
        create_notification(
            template=sample_email_template,
            to_field=Config.INTERNAL_TEST_EMAIL_ADDRESS,
            status="created",
            reply_to_text=sample_service.get_default_reply_to_email_address(),
        )
    )
    mocker.patch("app.delivery.send_to_providers.send_email_response", return_value="reference")
    send_mock = mocker.patch("app.aws_ses_client.send_email")
    send_to_providers.send_email_to_provider(notification)

    send_mock.assert_not_called()
    assert Notification.query.get(notification.id).status == "sending"


def test_send_email_to_provider_should_format_reply_to_email_address(sample_email_template, mocker):
    mocker.patch("app.aws_ses_client.send_email", return_value="reference")
    mocker.patch("app.delivery.send_to_providers.bounce_rate_client")

    db_notification = save_notification(create_notification(template=sample_email_template, reply_to_text="test@test.com\t"))

    send_to_providers.send_email_to_provider(
        db_notification,
    )

    app.aws_ses_client.send_email.assert_called_once_with(
        ANY,
        ANY,
        ANY,
        body=ANY,
        html_body=ANY,
        reply_to_address="test@test.com",
        attachments=[],
    )


def test_send_sms_to_provider_should_format_phone_number(sample_notification, mocker):
    sample_notification.to = "+1 650 253 2222"
    send_mock = mocker.patch("app.aws_sns_client.send_sms", return_value="message_id_from_sns")

    send_to_providers.send_sms_to_provider(sample_notification)

    assert send_mock.call_args[1]["to"] == "+16502532222"


def test_send_email_to_provider_should_format_email_address(sample_email_notification, mocker):
    sample_email_notification.to = "test@example.com\t"
    send_mock = mocker.patch("app.aws_ses_client.send_email", return_value="reference")
    mocker.patch("app.delivery.send_to_providers.bounce_rate_client")

    send_to_providers.send_email_to_provider(sample_email_notification)

    # to_addresses
    send_mock.assert_called_once_with(
        ANY,
        # to_addresses
        "test@example.com",
        ANY,
        body=ANY,
        html_body=ANY,
        reply_to_address=ANY,
        attachments=[],
    )


def test_file_attachment_retry(mocker, notify_db, notify_db_session):
    template = create_sample_email_template(notify_db, notify_db_session, content="Here is your ((file))")

    class mock_response:
        status_code = 200

        def json():
            return {"GuardDutyMalwareScanStatus": "NO_THREATS_FOUND"}

    mocker.patch("app.delivery.send_to_providers.document_download_client.check_scan_verdict", return_value=mock_response)

    personalisation = {
        "file": document_download_response(
            {
                "direct_file_url": "http://foo.bar/direct_file_url",
                "url": "http://foo.bar/url",
                "mime_type": "application/pdf",
            }
        )
    }
    personalisation["file"]["document"]["sending_method"] = "attach"
    personalisation["file"]["document"]["filename"] = "file.txt"
    personalisation["file"]["document"]["id"] = "1234"

    db_notification = save_notification(create_notification(template=template, personalisation=personalisation))

    mocker.patch("app.delivery.send_to_providers.statsd_client")
    mocker.patch("app.aws_ses_client.send_email", return_value="reference")

    # When a urllib3 request attempts retries and fails it will wrap the offending exception in a MaxRetryError
    # thus we'll capture the logged exception and assert it's a MaxRetryError to verify that retries were attempted
    mock_logger = mocker.patch("app.delivery.send_to_providers.current_app.logger.error")
    logger_args = []

    def mock_error(*args):
        logger_args.append(args)

    mock_logger.side_effect = mock_error

    class MockHTTPResponse:
        def __init__(self, status):
            self.status = status
            self.data = b"file content" if status == 200 else b""

    mock_http = mocker.patch("urllib3.PoolManager")
    mock_http.return_value.request.side_effect = [
        MockHTTPResponse(500),
        MockHTTPResponse(500),
        MockHTTPResponse(500),
        MockHTTPResponse(500),
        MockHTTPResponse(500),
    ]

    send_to_providers.send_email_to_provider(db_notification)
    exception = logger_args[0][0].split("Exception: ")[1]
    assert mock_logger.call_count == 1
    assert "Max retries exceeded" in exception


def test_file_attachment_max_retries(mocker, notify_db, notify_db_session):
    template = create_sample_email_template(notify_db, notify_db_session, content="Here is your ((file))")

    class mock_response:
        status_code = 200

        def json():
            return {"GuardDutyMalwareScanStatus": "NO_THREATS_FOUND"}

    mocker.patch("app.delivery.send_to_providers.document_download_client.check_scan_verdict", return_value=mock_response)

    personalisation = {
        "file": document_download_response(
            {
                "direct_file_url": "http://foo.bar/direct_file_url",
                "url": "http://foo.bar/url",
                "mime_type": "application/pdf",
            }
        )
    }
    personalisation["file"]["document"]["sending_method"] = "attach"
    personalisation["file"]["document"]["filename"] = "file.txt"

    db_notification = save_notification(create_notification(template=template, personalisation=personalisation))

    mocker.patch("app.delivery.send_to_providers.statsd_client")
    mocker.patch("app.aws_ses_client.send_email", return_value="reference")

    mock_logger = mocker.patch("app.delivery.send_to_providers.current_app.logger.error")
    send_to_providers.send_email_to_provider(db_notification)
    assert mock_logger.call_count == 1
    assert "Max retries exceeded" in mock_logger.call_args[0][0]


@pytest.mark.parametrize(
    "filename_attribute_present, filename, expected_filename",
    [
        (False, "whatever", None),
        (True, None, None),
        (True, "custom_filename.pdf", "custom_filename.pdf"),
    ],
)
def test_notification_document_with_pdf_attachment(
    mocker,
    notify_db,
    notify_db_session,
    filename_attribute_present,
    filename,
    expected_filename,
):
    template = create_sample_email_template(notify_db, notify_db_session, content="Here is your ((file))")
    mocker.patch("app.delivery.send_to_providers.bounce_rate_client")

    class mock_response:
        status_code = 200

        def json():
            return {"GuardDutyMalwareScanStatus": "NO_THREATS_FOUND"}

    mocker.patch("app.delivery.send_to_providers.document_download_client.check_scan_verdict", return_value=mock_response)

    personalisation = {
        "file": document_download_response(
            {
                "direct_file_url": "http://foo.bar/direct_file_url",
                "url": "http://foo.bar/url",
                "mime_type": "application/pdf",
            }
        )
    }
    if filename_attribute_present:
        personalisation["file"]["document"]["filename"] = filename
        personalisation["file"]["document"]["sending_method"] = "attach"
    else:
        personalisation["file"]["document"]["sending_method"] = "link"

    db_notification = save_notification(create_notification(template=template, personalisation=personalisation))

    statsd_mock = mocker.patch("app.delivery.send_to_providers.statsd_client")
    send_mock = mocker.patch("app.aws_ses_client.send_email", return_value="reference")
    mocker.patch("app.delivery.send_to_providers.Retry")

    response_return_mock = MagicMock()
    response_return_mock.status = 200
    response_return_mock.data = "Hello there!"

    response_mock = mocker.patch(
        "app.delivery.send_to_providers.PoolManager.request",
        return_value=response_return_mock,
    )

    send_to_providers.send_email_to_provider(db_notification)

    attachments = []
    if filename_attribute_present:
        response_mock.assert_called_with("GET", url="http://foo.bar/direct_file_url")
        attachments = [
            {
                "name": expected_filename,
                "data": "Hello there!",
                "mime_type": "application/pdf",
            }
        ]
    send_mock.assert_called_once_with(
        ANY,
        ANY,
        ANY,
        body=ANY,
        html_body=ANY,
        reply_to_address=ANY,
        attachments=attachments,
    )
    if not filename_attribute_present:
        assert "http://foo.bar/url" in send_mock.call_args[1]["html_body"]

    notification = Notification.query.get(db_notification.id)
    assert notification.status == "sending"

    if attachments:
        statsd_calls = statsd_mock.timing_with_dates.call_args_list
        statsd_key = "email.with-attachments.process_type-normal"
        assert call(statsd_key, notification.sent_at, notification.created_at) in statsd_calls
        assert call(statsd_key) in statsd_mock.incr.call_args_list


@pytest.mark.parametrize(
    "sending_method",
    [
        ("attach"),
        ("link"),
    ],
)
def test_notification_with_bad_file_attachment_url(mocker, notify_db, notify_db_session, sending_method):
    template = create_sample_email_template(notify_db, notify_db_session, content="Here is your ((file))")
    personalisation = {
        "file": document_download_response(
            {
                "direct_file_url": "file://foo.bar/file.txt" if sending_method == "attach" else "http://foo.bar/file.txt",
                "url": "file://foo.bar/file.txt" if sending_method == "link" else "http://foo.bar/file.txt",
                "mime_type": "application/pdf",
            }
        )
    }
    personalisation["file"]["document"]["sending_method"] = sending_method
    if sending_method == "attach":
        personalisation["file"]["document"]["filename"] = "file.txt"

    db_notification = save_notification(create_notification(template=template, personalisation=personalisation))

    mocker.patch("app.delivery.send_to_providers.Retry")

    with pytest.raises(InvalidUrlException):
        send_to_providers.send_email_to_provider(db_notification)


def test_notification_raises_error_if_message_contains_sin_pii_that_passes_luhn(
    sample_email_template_with_html, mocker, notify_api
):
    send_mock = mocker.patch("app.aws_ses_client.send_email", return_value="reference")

    db_notification = save_notification(
        create_notification(
            template=sample_email_template_with_html,
            to_field="jo.smith@example.com",
            personalisation={"name": "046-454-286"},
        )
    )

    with set_config_values(
        notify_api,
        {
            "SCAN_FOR_PII": "True",
        },
    ):
        with pytest.raises(NotificationTechnicalFailureException) as e:
            send_to_providers.send_email_to_provider(db_notification)
            assert db_notification.id in e.value

    send_mock.assert_not_called()

    assert Notification.query.get(db_notification.id).status == "pii-check-failed"


def test_notification_passes_if_message_contains_sin_pii_that_fails_luhn(sample_email_template_with_html, mocker, notify_api):
    send_mock = mocker.patch("app.aws_ses_client.send_email", return_value="reference")
    mocker.patch("app.delivery.send_to_providers.bounce_rate_client")

    db_notification = save_notification(
        create_notification(
            template=sample_email_template_with_html,
            to_field="jo.smith@example.com",
            personalisation={"name": "123-456-789"},
        )
    )

    send_to_providers.send_email_to_provider(db_notification)

    send_mock.assert_called()

    assert Notification.query.get(db_notification.id).status == "sending"


def test_notification_passes_if_message_contains_phone_number(sample_email_template_with_html, mocker):
    send_mock = mocker.patch("app.aws_ses_client.send_email", return_value="reference")
    mocker.patch("app.delivery.send_to_providers.bounce_rate_client")

    db_notification = save_notification(
        create_notification(
            template=sample_email_template_with_html,
            to_field="jo.smith@example.com",
            personalisation={"name": "123-456-7890"},
        )
    )

    send_to_providers.send_email_to_provider(db_notification)

    send_mock.assert_called()

    assert Notification.query.get(db_notification.id).status == "sending"


def test_is_service_allowed_html(sample_service: Service, notify_api):
    assert not send_to_providers.is_service_allowed_html(sample_service)
    with set_config_values(
        notify_api,
        {
            "ALLOW_HTML_SERVICE_IDS": str(sample_service.id),
        },
    ):
        assert send_to_providers.is_service_allowed_html(sample_service)


class TestMalware:
    def test_send_to_providers_fails_if_malware_detected(self, sample_email_template, mocker):
        send_mock = mocker.patch("app.aws_ses_client.send_email", return_value="reference")

        class mock_response:
            status_code = 423

            def json():
                return {"GuardDutyMalwareScanStatus": "THREATS_FOUND"}

        mocker.patch("app.delivery.send_to_providers.document_download_client.check_scan_verdict", return_value=mock_response)
        personalisation = {"file": document_download_response()}

        db_notification = save_notification(create_notification(template=sample_email_template, personalisation=personalisation))

        with pytest.raises(MalwareDetectedException) as e:
            send_to_providers.send_email_to_provider(db_notification)
            assert db_notification.id in e.value
        send_mock.assert_not_called()

        assert Notification.query.get(db_notification.id).status == "virus-scan-failed"

    def test_send_to_providers_fails_if_malware_scan_in_progress(self, sample_email_template, mocker):
        send_mock = mocker.patch("app.aws_ses_client.send_email", return_value="reference")

        class mock_response:
            status_code = 428

            def json():
                return {}

        mocker.patch("app.delivery.send_to_providers.document_download_client.check_scan_verdict", return_value=mock_response)
        personalisation = {"file": document_download_response()}

        db_notification = save_notification(create_notification(template=sample_email_template, personalisation=personalisation))

        with pytest.raises(MalwareScanInProgressException) as e:
            send_to_providers.send_email_to_provider(db_notification)
            assert db_notification.id in e.value
        send_mock.assert_not_called()

        assert Notification.query.get(db_notification.id).status == "created"

    @pytest.mark.parametrize(
        "status_code_returned, scan_verdict",
        [
            (200, "clean"),
            (408, "scan_timed_out"),
            (422, "scan_unsupported"),
            (422, "scan_failed"),
        ],
    )
    def test_send_to_providers_succeeds_if_malware_verdict_clean(
        self, sample_email_template, mocker, status_code_returned, scan_verdict
    ):
        send_mock = mocker.patch("app.aws_ses_client.send_email", return_value="reference")
        mocker.patch("app.delivery.send_to_providers.bounce_rate_client")

        class mock_response:
            status_code = status_code_returned

            def json():
                return {"GuardDutyMalwareScanStatus": scan_verdict}

        mocker.patch("app.delivery.send_to_providers.document_download_client.check_scan_verdict", return_value=mock_response)
        personalisation = {"file": document_download_response()}

        db_notification = save_notification(create_notification(template=sample_email_template, personalisation=personalisation))

        send_to_providers.send_email_to_provider(db_notification)
        send_mock.assert_called_once()

        assert Notification.query.get(db_notification.id).status == "sending"

    def test_send_to_providers_fails_if_document_download_internal_error(self, sample_email_template, mocker):
        send_mock = mocker.patch("app.aws_ses_client.send_email", return_value="reference")

        class mock_response:
            status_code = 404

            def json():
                return {"GuardDutyMalwareScanStatus": "None"}

        mocker.patch("app.delivery.send_to_providers.document_download_client.check_scan_verdict", return_value=mock_response)
        personalisation = {"file": document_download_response()}

        db_notification = save_notification(create_notification(template=sample_email_template, personalisation=personalisation))

        with pytest.raises(DocumentDownloadException) as e:
            send_to_providers.send_email_to_provider(db_notification)
            assert db_notification.id in e.value
        send_mock.assert_not_called()

        assert Notification.query.get(db_notification.id).status == "technical-failure"


class TestBounceRate:
    def test_send_email_should_use_service_reply_to_email(self, sample_service, sample_email_template, mocker, notify_api):
        mocker.patch("app.aws_ses_client.send_email", return_value="reference")
        mocker.patch("app.bounce_rate_client.set_sliding_notifications")
        db_notification = save_notification(create_notification(template=sample_email_template, reply_to_text="foo@bar.com"))
        create_reply_to_email(service=sample_service, email_address="foo@bar.com")

        send_to_providers.send_email_to_provider(
            db_notification,
        )
        app.bounce_rate_client.set_sliding_notifications.assert_called_once_with(sample_service.id, str(db_notification.id))

    def test_check_service_over_bounce_rate_critical(self, mocker: MockFixture, notify_api, fake_uuid):
        with notify_api.app_context():
            mocker.patch("app.bounce_rate_client.check_bounce_rate_status", return_value=BounceRateStatus.CRITICAL.value)
            mocker.patch("app.bounce_rate_client.get_bounce_rate", return_value=current_app.config["BR_CRITICAL_PERCENTAGE"])
            mock_logger = mocker.patch("app.delivery.send_to_providers.current_app.logger.warning")
            send_to_providers.check_service_over_bounce_rate(fake_uuid)
            mock_logger.assert_called_once_with(
                f"Service: {fake_uuid} has met or exceeded a critical bounce rate threshold of 10%. Bounce rate: {current_app.config['BR_CRITICAL_PERCENTAGE']}"
            )

    def test_check_service_over_bounce_rate_warning(self, mocker: MockFixture, notify_api, fake_uuid):
        with notify_api.app_context():
            mocker.patch("app.bounce_rate_client.check_bounce_rate_status", return_value=BounceRateStatus.WARNING.value)
            mocker.patch("app.bounce_rate_client.get_bounce_rate", return_value=current_app.config["BR_WARNING_PERCENTAGE"])
            mock_logger = mocker.patch("app.notifications.validators.current_app.logger.warning")
            send_to_providers.check_service_over_bounce_rate(fake_uuid)
            mock_logger.assert_called_once_with(
                f"Service: {fake_uuid} has met or exceeded a warning bounce rate threshold of 5%. Bounce rate: {current_app.config['BR_WARNING_PERCENTAGE']}"
            )

    def test_check_service_over_bounce_rate_normal(self, mocker: MockFixture, notify_api, fake_uuid):
        with notify_api.app_context():
            mocker.patch("app.bounce_rate_client.check_bounce_rate_status", return_value=BounceRateStatus.NORMAL.value)
            mocker.patch("app.bounce_rate_client.get_bounce_rate", return_value=0.0)
            mock_logger = mocker.patch("app.notifications.validators.current_app.logger.warning")
            assert send_to_providers.check_service_over_bounce_rate(fake_uuid) is None
            mock_logger.assert_not_called()


@pytest.mark.parametrize(
    "encoded_text, charset, encoding, expected",
    [
        ("hello_world", "utf-8", "B", "=?utf-8?B?hello_world?="),
        ("hello_world", "utf-8", "Q", "=?utf-8?Q?hello_world?="),
        ("hello_world2", "utf-8", "B", "=?utf-8?B?hello_world2?="),
    ],
)
def test_mime_encoded_word_syntax_encoding(encoded_text, charset, encoding, expected):
    result = send_to_providers.mime_encoded_word_syntax(encoded_text=encoded_text, charset=charset, encoding=encoding)
    assert result == expected


class TestGetFromAddress(TestCase):
    def test_get_from_address_ascii(self):
        # Arrange
        friendly_from = "John Doe"
        email_from = "johndoe"
        sending_domain = "example.com"

        # Act
        result = send_to_providers.get_from_address(friendly_from, email_from, sending_domain)

        # Assert
        expected_result = '"=?utf-8?B?Sm9obiBEb2U=?=" <johndoe@example.com>'
        self.assertEqual(result, expected_result)

    def test_get_from_address_non_ascii(self):
        # Arrange
        friendly_from = "Jöhn Döe"
        email_from = "johndoe"
        sending_domain = "example.com"

        # Act
        result = send_to_providers.get_from_address(friendly_from, email_from, sending_domain)

        # Assert
        expected_result = '"=?utf-8?B?SsO2aG4gRMO2ZQ==?=" <johndoe@example.com>'
        self.assertEqual(result, expected_result)

    def test_get_from_address_empty_friendly_from(self):
        # Arrange
        friendly_from = ""
        email_from = "johndoe"
        sending_domain = "example.com"

        # Act
        result = send_to_providers.get_from_address(friendly_from, email_from, sending_domain)

        # Assert
        expected_result = '"=?utf-8?B??=" <johndoe@example.com>'
        self.assertEqual(result, expected_result)
