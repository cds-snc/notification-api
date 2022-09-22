import uuid
from datetime import datetime
from unittest.mock import ANY

import pytest
import os

from flask import current_app
from notifications_utils.recipients import validate_and_format_phone_number
from requests import HTTPError

import app
from app import aws_sns_client, mmg_client, ProviderService
from app.clients.email import EmailClient
from app.dao import (provider_details_dao, notifications_dao)
from app.dao.provider_details_dao import dao_switch_sms_provider_to_provider_with_identifier
from app.delivery import send_to_providers
from app.delivery.send_to_providers import load_provider
from app.exceptions import NotificationTechnicalFailureException, InvalidProviderException
from app.feature_flags import FeatureFlag

from app.models import (
    Notification,
    EmailBranding,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEST,
    KEY_TYPE_TEAM,
    BRANDING_ORG,
    BRANDING_BOTH,
    BRANDING_ORG_BANNER, ProviderDetails, EMAIL_TYPE, TemplateBase, Service, NOTIFICATION_SENDING,
    NOTIFICATION_DELIVERED
)

from tests.app.db import (
    create_service,
    create_template,
    create_notification,
    create_reply_to_email,
    create_service_sms_sender,
    create_service_with_defined_sms_sender
)

from tests.conftest import set_config_values


@pytest.fixture
def mock_source_email_address(mocker):
    source_email_address = '"Some Name" <some-user@some.domain>'
    mock_compute_function = mocker.patch(
        'app.delivery.send_to_providers.compute_source_email_address',
        return_value=source_email_address
    )
    return (source_email_address, mock_compute_function)


def test_should_return_highest_priority_active_provider(restore_provider_details, sample_notification):
    providers = provider_details_dao.get_provider_details_by_notification_type('sms')

    first = providers[0]
    second = providers[1]

    assert send_to_providers.provider_to_use(sample_notification).name == first.identifier

    first.priority, second.priority = second.priority, first.priority

    provider_details_dao.dao_update_provider_details(first)
    provider_details_dao.dao_update_provider_details(second)

    assert send_to_providers.provider_to_use(sample_notification).name == second.identifier

    first.priority, second.priority = second.priority, first.priority
    first.active = False

    provider_details_dao.dao_update_provider_details(first)
    provider_details_dao.dao_update_provider_details(second)

    assert send_to_providers.provider_to_use(sample_notification).name == second.identifier

    first.active = True
    provider_details_dao.dao_update_provider_details(first)

    assert send_to_providers.provider_to_use(sample_notification).name == first.identifier


def test_should_not_use_active_but_disabled_provider(mocker):
    active_provider = mocker.Mock(active=True)
    mocker.patch(
        'app.delivery.send_to_providers.get_provider_details_by_notification_type',
        return_value=[active_provider]
    )

    mocker.patch(
        'app.delivery.send_to_providers.is_provider_enabled',
        return_value=False
    )

    with pytest.raises(Exception, match="No active email providers"):
        send_to_providers.provider_to_use(mocker.Mock(Notification, notification_type=EMAIL_TYPE))


def test_should_send_personalised_template_to_correct_sms_provider_and_persist(
    sample_sms_template_with_html,
    mock_sms_client
):
    db_notification = create_notification(template=sample_sms_template_with_html,
                                          to_field="+16502532222", personalisation={"name": "Jo"},
                                          status='created',
                                          reply_to_text=sample_sms_template_with_html.service.get_default_sms_sender())

    send_to_providers.send_sms_to_provider(
        db_notification
    )

    mock_sms_client.send_sms.assert_called_once_with(
        to=validate_and_format_phone_number("+16502532222"),
        content="Sample service: Hello Jo\nHere is <em>some HTML</em> & entities",
        reference=str(db_notification.id),
        sender=current_app.config['FROM_NUMBER'],
        service_id=ANY,
        sms_sender_id=ANY
    )

    notification = Notification.query.filter_by(id=db_notification.id).one()

    assert notification.status == NOTIFICATION_SENDING
    assert notification.sent_at <= datetime.utcnow()
    assert notification.sent_by == mock_sms_client.get_name()
    assert notification.billable_units == 1
    assert notification.personalisation == {"name": "Jo"}
    assert notification.reference == "some-reference"


def test_send_email_to_provider_should_compute_source_email_address(
    sample_email_template_with_html,
    mock_email_client,
    mocked_build_ga_pixel_url,
    notify_api,
    mock_source_email_address
):
    db_notification = create_notification(
        template=sample_email_template_with_html,
        to_field="jo.smith@example.com",
        personalisation={'name': 'Jo'}
    )
    mock_compute_email_from = mock_source_email_address[1]

    send_to_providers.send_email_to_provider(db_notification)

    mock_compute_email_from.assert_called_once_with(db_notification.service, mock_email_client)


def test_should_send_personalised_template_to_correct_email_provider_and_persist(
    sample_email_template_with_html,
    mock_email_client,
    mocked_build_ga_pixel_url,
    notify_api,
    mock_source_email_address
):
    db_notification = create_notification(
        template=sample_email_template_with_html,
        to_field="jo.smith@example.com",
        personalisation={'name': 'Jo'}
    )

    with set_config_values(notify_api, {
        'NOTIFY_EMAIL_FROM_NAME': 'Default Name'
    }):
        send_to_providers.send_email_to_provider(db_notification)

    mock_email_client.send_email.assert_called_once_with(
        source=mock_source_email_address[0],
        to_addresses='jo.smith@example.com',
        subject='Jo <em>some HTML</em>',
        body='Hello Jo\nThis is an email from GOV.\u200bUK with <em>some HTML</em>\n',
        html_body=ANY,
        reply_to_address=None,
        attachments=[]
    )

    assert '<!DOCTYPE html' in mock_email_client.send_email.call_args[1]['html_body']
    assert '&lt;em&gt;some HTML&lt;/em&gt;' in mock_email_client.send_email.call_args[1]['html_body']

    notification = Notification.query.filter_by(id=db_notification.id).one()
    assert notification.status == 'sending'
    assert notification.sent_at <= datetime.utcnow()
    assert notification.sent_by == mock_email_client.get_name()
    assert notification.personalisation == {"name": "Jo"}


def test_should_not_send_email_message_when_service_is_inactive_notification_is_in_tech_failure(
        sample_service,
        sample_notification,
        mock_email_client,
        mocked_build_ga_pixel_url
):
    sample_service.active = False

    with pytest.raises(NotificationTechnicalFailureException) as e:
        send_to_providers.send_email_to_provider(sample_notification)
    assert str(sample_notification.id) in str(e.value)
    mock_email_client.send_email.assert_not_called()
    assert Notification.query.get(sample_notification.id).status == 'technical-failure'


@pytest.mark.parametrize("client_send", ["app.aws_sns_client.send_sms", "app.mmg_client.send_sms"])
def test_should_not_send_sms_message_when_service_is_inactive_notifcation_is_in_tech_failure(
        sample_service, sample_notification, mocker, client_send):
    sample_service.active = False
    send_mock = mocker.patch(client_send, return_value='reference')

    with pytest.raises(NotificationTechnicalFailureException) as e:
        send_to_providers.send_sms_to_provider(sample_notification)
    assert str(sample_notification.id) in str(e.value)
    send_mock.assert_not_called()
    assert Notification.query.get(sample_notification.id).status == 'technical-failure'


def test_send_sms_should_use_template_version_from_notification_not_latest(
        sample_template,
        mock_sms_client):
    db_notification = create_notification(template=sample_template, to_field='+16502532222', status='created',
                                          reply_to_text=sample_template.service.get_default_sms_sender())

    sample_template.service.prefix_sms = True
    version_on_notification = sample_template.version

    # Change the template
    from app.dao.templates_dao import dao_update_template, dao_get_template_by_id
    sample_template.content = sample_template.content + " another version of the template"
    dao_update_template(sample_template)
    t = dao_get_template_by_id(sample_template.id)
    assert t.version > version_on_notification

    send_to_providers.send_sms_to_provider(
        db_notification
    )

    mock_sms_client.send_sms.assert_called_once_with(
        to=validate_and_format_phone_number("+16502532222"),
        content="Sample service: This is a template:\nwith a newline",
        reference=str(db_notification.id),
        sender=current_app.config['FROM_NUMBER'],
        service_id=ANY,
        sms_sender_id=ANY
    )

    persisted_notification = notifications_dao.get_notification_by_id(db_notification.id)
    assert persisted_notification.to == db_notification.to
    assert persisted_notification.template_id == sample_template.id
    assert persisted_notification.template_version == version_on_notification
    assert persisted_notification.template_version != sample_template.version
    assert persisted_notification.status == NOTIFICATION_SENDING
    assert not persisted_notification.personalisation


@pytest.mark.parametrize('research_mode,key_type', [
    (True, KEY_TYPE_NORMAL),
    (False, KEY_TYPE_TEST)
])
def test_should_call_send_sms_response_task_if_research_mode(
        notify_db, sample_service, sample_notification, mocker, mock_sms_client, research_mode, key_type
):
    mocker.patch('app.delivery.send_to_providers.send_sms_response')

    if research_mode:
        sample_service.research_mode = True
        notify_db.session.add(sample_service)
        notify_db.session.commit()

    sample_notification.key_type = key_type
    sample_notification.reference = None

    send_to_providers.send_sms_to_provider(
        sample_notification
    )
    assert not mock_sms_client.send_sms.called

    app.delivery.send_to_providers.send_sms_response.assert_called_once_with(
        mock_sms_client.get_name(), str(sample_notification.id), sample_notification.to, sample_notification.reference
    )

    persisted_notification = notifications_dao.get_notification_by_id(sample_notification.id)
    assert persisted_notification.to == sample_notification.to
    assert persisted_notification.template_id == sample_notification.template_id
    assert persisted_notification.status == NOTIFICATION_SENDING
    assert persisted_notification.sent_at <= datetime.utcnow()
    assert persisted_notification.sent_by == mock_sms_client.get_name()
    assert persisted_notification.reference
    assert not persisted_notification.personalisation


def test_should_have_sent_status_if_fake_callback_function_fails(sample_notification, mocker, mock_sms_client):
    mocker.patch('app.delivery.send_to_providers.send_sms_response', side_effect=HTTPError)

    sample_notification.key_type = KEY_TYPE_TEST

    with pytest.raises(HTTPError):
        send_to_providers.send_sms_to_provider(
            sample_notification
        )
    assert sample_notification.status == NOTIFICATION_SENDING
    assert sample_notification.sent_by == mock_sms_client.get_name()


def test_should_not_send_to_provider_when_status_is_not_created(
    sample_template,
    mocker
):
    notification = create_notification(template=sample_template, status='sending')
    mocker.patch('app.aws_sns_client.send_sms')
    response_mock = mocker.patch('app.delivery.send_to_providers.send_sms_response')

    send_to_providers.send_sms_to_provider(
        notification
    )

    app.aws_sns_client.send_sms.assert_not_called()
    response_mock.assert_not_called()


def test_should_send_sms_with_downgraded_content(notify_db_session, mock_sms_client):
    # é, o, and u are in GSM.
    # á, ï, grapes, tabs, zero width space and ellipsis are not
    msg = "á é ï o u 🍇 foo\tbar\u200bbaz((misc))…"
    placeholder = '∆∆∆abc'
    gsm_message = "?odz Housing Service: a é i o u ? foo barbaz???abc..."
    service = create_service(service_name='Łódź Housing Service', prefix_sms=True)
    template = create_template(service, content=msg)
    db_notification = create_notification(
        template=template,
        personalisation={'misc': placeholder}
    )

    send_to_providers.send_sms_to_provider(db_notification)

    mock_sms_client.send_sms.assert_called_once_with(
        to=ANY,
        content=gsm_message,
        reference=ANY,
        sender=ANY,
        service_id=ANY,
        sms_sender_id=ANY
    )


def test_send_sms_should_use_service_sms_sender(
        sample_service,
        sample_template,
        mock_sms_client):
    sms_sender = create_service_sms_sender(service=sample_service, sms_sender='123456', is_default=False)
    db_notification = create_notification(template=sample_template, reply_to_text=sms_sender.sms_sender)

    send_to_providers.send_sms_to_provider(
        db_notification,
    )

    mock_sms_client.send_sms.assert_called_once_with(
        to=ANY,
        content=ANY,
        reference=ANY,
        sender=sms_sender.sms_sender,
        service_id=ANY,
        sms_sender_id=ANY
    )


@pytest.mark.parametrize('research_mode,key_type', [
    (True, KEY_TYPE_NORMAL),
    (False, KEY_TYPE_TEST)
])
def test_send_email_to_provider_should_call_research_mode_task_response_task_if_research_mode(
        sample_service,
        sample_email_template,
        mocker,
        mock_email_client,
        mocked_build_ga_pixel_url,
        research_mode,
        key_type):
    notification = create_notification(
        template=sample_email_template,
        to_field="john@smith.com",
        key_type=key_type,
        billable_units=0
    )
    sample_service.research_mode = research_mode

    reference = uuid.uuid4()
    mocker.patch('app.uuid.uuid4', return_value=reference)
    mocker.patch('app.delivery.send_to_providers.send_email_response')

    send_to_providers.send_email_to_provider(
        notification
    )

    assert not mock_email_client.send_email.called
    app.delivery.send_to_providers.send_email_response.assert_called_once_with(str(reference), 'john@smith.com')
    persisted_notification = Notification.query.filter_by(id=notification.id).one()
    assert persisted_notification.to == 'john@smith.com'
    assert persisted_notification.template_id == sample_email_template.id
    assert persisted_notification.status == 'sending'
    assert persisted_notification.sent_at <= datetime.utcnow()
    assert persisted_notification.created_at <= datetime.utcnow()
    assert persisted_notification.sent_by == mock_email_client.get_name()
    assert persisted_notification.reference == str(reference)
    assert persisted_notification.billable_units == 0


def test_send_email_to_provider_should_not_send_to_provider_when_status_is_not_created(
    sample_email_template,
    mocker
):
    notification = create_notification(template=sample_email_template, status='sending')
    mocker.patch('app.aws_ses_client.send_email')
    mocker.patch('app.delivery.send_to_providers.send_email_response')

    send_to_providers.send_sms_to_provider(
        notification
    )
    app.aws_ses_client.send_email.assert_not_called()
    app.delivery.send_to_providers.send_email_response.assert_not_called()


def test_send_email_should_use_service_reply_to_email(
        sample_service,
        sample_email_template,
        mock_email_client,
        mocked_build_ga_pixel_url
):
    db_notification = create_notification(template=sample_email_template, reply_to_text='foo@bar.com')
    create_reply_to_email(service=sample_service, email_address='foo@bar.com')

    send_to_providers.send_email_to_provider(db_notification)

    _, kwargs = mock_email_client.send_email.call_args
    assert kwargs['reply_to_address'] == 'foo@bar.com'


def test_get_html_email_renderer_should_return_for_normal_service(
        sample_notification_model_with_organization,
        mock_email_client
):
    options = send_to_providers.get_html_email_options(
        sample_notification_model_with_organization,
        mock_email_client)
    assert options['default_banner'] is True
    assert 'brand_colour' not in options.keys()
    assert 'brand_logo' not in options.keys()
    assert 'brand_text' not in options.keys()
    assert 'brand_name' not in options.keys()
    assert 'ga_pixel_url' in options.keys()


@pytest.mark.parametrize('branding_type, default_banner', [
    (BRANDING_ORG, False),
    (BRANDING_BOTH, True),
    (BRANDING_ORG_BANNER, False)
])
def test_get_html_email_renderer_with_branding_details(
        branding_type,
        default_banner,
        sample_notification_model_with_organization,
        mock_email_client
):

    email_branding = EmailBranding(
        brand_type=branding_type,
        colour='#000000',
        logo='justice-league.png',
        name='Justice League',
        text='League of Justice',
    )
    sample_notification_model_with_organization.service.email_branding = email_branding

    options = send_to_providers.get_html_email_options(
        sample_notification_model_with_organization,
        mock_email_client
    )

    assert options['default_banner'] == default_banner
    assert options['brand_colour'] == '#000000'
    assert options['brand_text'] == 'League of Justice'
    assert options['brand_name'] == 'Justice League'

    if branding_type == BRANDING_ORG_BANNER:
        assert options['brand_banner'] is True
    else:
        assert options['brand_banner'] is False


def test_get_html_email_renderer_with_branding_details_and_render_default_banner_only(
        sample_notification_model_with_organization,
        mock_email_client
):
    sample_notification_model_with_organization.service.email_branding = None

    options = send_to_providers.get_html_email_options(
        sample_notification_model_with_organization,
        mock_email_client
    )

    assert {'default_banner': True, 'brand_banner': False}.items() <= options.items()


def test_get_html_email_renderer_prepends_logo_path(
        notify_api,
        sample_notification_model_with_organization,
        mock_email_client
):
    email_branding = EmailBranding(
        brand_type=BRANDING_ORG,
        colour='#000000',
        logo='justice-league.png',
        name='Justice League',
        text='League of Justice',
    )
    sample_notification_model_with_organization.service.email_branding = email_branding

    renderer = send_to_providers.get_html_email_options(sample_notification_model_with_organization, mock_email_client)
    domain = "https://dev-notifications-va-gov-assets.s3.amazonaws.com"
    assert renderer['brand_logo'] == "{}{}".format(domain, '/justice-league.png')


def test_get_html_email_renderer_handles_email_branding_without_logo(
        notify_api,
        sample_notification_model_with_organization,
        mock_email_client
):
    email_branding = EmailBranding(
        brand_type=BRANDING_ORG_BANNER,
        colour='#000000',
        logo=None,
        name='Justice League',
        text='League of Justice',
    )

    sample_notification_model_with_organization.service.email_branding = email_branding

    renderer = send_to_providers.get_html_email_options(sample_notification_model_with_organization, mock_email_client)

    assert renderer['default_banner'] is False
    assert renderer['brand_banner'] is True
    assert renderer['brand_logo'] is None
    assert renderer['brand_text'] == 'League of Justice'
    assert renderer['brand_colour'] == '#000000'
    assert renderer['brand_name'] == 'Justice League'


@pytest.mark.parametrize('base_url, expected_url', [
    # don't change localhost to prevent errors when testing locally
    ('http://localhost:6012', 'filename.png'),
    ('https://www.notifications.service.gov.uk', 'filename.png'),
])
def test_get_logo_url_works_for_different_environments(base_url, expected_url):
    logo_file = 'filename.png'

    logo_url = send_to_providers.get_logo_url(base_url, logo_file)
    domain = "dev-notifications-va-gov-assets.s3.amazonaws.com"
    assert logo_url == "https://{}/{}".format(domain, expected_url)


def test_should_not_update_notification_if_research_mode_on_exception(
        sample_service, sample_notification, mocker
):
    mocker.patch('app.delivery.send_to_providers.send_sms_response', side_effect=Exception())
    update_mock = mocker.patch('app.delivery.send_to_providers.update_notification_to_sending')
    sample_service.research_mode = True
    sample_notification.billable_units = 0

    with pytest.raises(Exception):
        send_to_providers.send_sms_to_provider(
            sample_notification
        )

    persisted_notification = notifications_dao.get_notification_by_id(sample_notification.id)
    assert persisted_notification.billable_units == 0
    assert update_mock.called


def __update_notification(notification_to_update, research_mode, expected_status):
    if research_mode or notification_to_update.key_type == KEY_TYPE_TEST:
        notification_to_update.status = expected_status


@pytest.mark.parametrize('research_mode,key_type, billable_units, expected_status', [
    (True, KEY_TYPE_NORMAL, 0, NOTIFICATION_DELIVERED),
    (False, KEY_TYPE_NORMAL, 1, NOTIFICATION_SENDING),
    (False, KEY_TYPE_TEST, 0, NOTIFICATION_SENDING),
    (True, KEY_TYPE_TEST, 0, NOTIFICATION_SENDING),
    (True, KEY_TYPE_TEAM, 0, NOTIFICATION_DELIVERED),
    (False, KEY_TYPE_TEAM, 1, NOTIFICATION_SENDING)
])
def test_should_update_billable_units_and_status_according_to_research_mode_and_key_type(
    sample_template,
    mocker,
    mock_sms_client,
    research_mode,
    key_type,
    billable_units,
    expected_status
):
    notification = create_notification(template=sample_template, billable_units=0, status='created', key_type=key_type)
    mocker.patch('app.delivery.send_to_providers.send_sms_response',
                 side_effect=__update_notification(notification, research_mode, expected_status))

    if research_mode:
        sample_template.service.research_mode = True

    send_to_providers.send_sms_to_provider(
        notification
    )
    assert notification.billable_units == billable_units
    assert notification.status == expected_status


def test_should_set_notification_billable_units_if_sending_to_provider_fails(
    sample_notification,
    mocker,
):
    mocker.patch('app.aws_sns_client.send_sms', side_effect=Exception())
    mock_toggle_provider = mocker.patch('app.delivery.send_to_providers.dao_toggle_sms_provider')

    sample_notification.billable_units = 0
    assert sample_notification.sent_by is None

    with pytest.raises(Exception):
        send_to_providers.send_sms_to_provider(sample_notification)

    assert sample_notification.billable_units == 1
    assert mock_toggle_provider.called


@pytest.mark.skip(reason="Currently not supporting international providers")
def test_should_send_sms_to_international_providers(
    restore_provider_details,
    sample_sms_template_with_html,
    sample_user,
    mocker
):
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=sample_user)

    dao_switch_sms_provider_to_provider_with_identifier('firetext')

    db_notification_uk = create_notification(
        template=sample_sms_template_with_html,
        to_field="+16135555555",
        personalisation={"name": "Jo"},
        status='created',
        international=False,
        reply_to_text=sample_sms_template_with_html.service.get_default_sms_sender()
    )

    db_notification_international = create_notification(
        template=sample_sms_template_with_html,
        to_field="+1613555555",
        personalisation={"name": "Jo"},
        status='created',
        international=False,
        reply_to_text=sample_sms_template_with_html.service.get_default_sms_sender()
    )

    mocker.patch('app.aws_sns_client.send_sms')
    mocker.patch('app.mmg_client.send_sms')

    send_to_providers.send_sms_to_provider(
        db_notification_uk
    )

    mmg_client.send_sms.assert_called_once_with(
        to="16135555555",
        content=ANY,
        reference=str(db_notification_uk.id),
        sender=current_app.config['FROM_NUMBER'],
        sms_sender_id=ANY
    )

    send_to_providers.send_sms_to_provider(
        db_notification_international
    )

    aws_sns_client.send_sms.assert_called_once_with(
        to="601117224412",
        content=ANY,
        reference=str(db_notification_international.id),
        sender=current_app.config['FROM_NUMBER'],
        sms_sender_id=ANY
    )

    notification_uk = Notification.query.filter_by(id=db_notification_uk.id).one()
    notification_int = Notification.query.filter_by(id=db_notification_international.id).one()

    assert notification_uk.status == 'sending'
    assert notification_uk.sent_by == 'firetext'
    assert notification_int.status == 'sent'
    assert notification_int.sent_by == 'mmg'


@pytest.mark.parametrize('sms_sender, expected_sender, prefix_sms, expected_content', [
    ('foo', 'foo', False, 'bar'),
    ('foo', 'foo', True, 'Sample service: bar'),
    # if 40604 is actually in DB then treat that as if entered manually
    ('40604', '40604', False, 'bar'),
    # 'testing' is the FROM_NUMBER during unit tests
    ('testing', 'testing', True, 'Sample service: bar'),
    ('testing', 'testing', False, 'bar'),
])
def test_should_handle_sms_sender_and_prefix_message(
    mock_sms_client,
    sms_sender,
    prefix_sms,
    expected_sender,
    expected_content,
    notify_db_session
):
    service = create_service_with_defined_sms_sender(sms_sender_value=sms_sender, prefix_sms=prefix_sms)
    template = create_template(service, content='bar')
    notification = create_notification(template, reply_to_text=sms_sender)

    send_to_providers.send_sms_to_provider(notification)

    mock_sms_client.send_sms.assert_called_once_with(
        content=expected_content,
        sender=expected_sender,
        to=ANY,
        reference=ANY,
        service_id=ANY,
        sms_sender_id=ANY
    )


def test_send_email_to_provider_uses_reply_to_from_notification(
        sample_email_template,
        mock_email_client,
        mocked_build_ga_pixel_url
):
    db_notification = create_notification(template=sample_email_template, reply_to_text="test@test.com")

    send_to_providers.send_email_to_provider(db_notification)

    _, kwargs = mock_email_client.send_email.call_args
    assert kwargs['reply_to_address'] == "test@test.com"


def test_send_email_to_provider_should_format_reply_to_email_address(
        sample_email_template,
        mock_email_client,
        mocked_build_ga_pixel_url
):
    db_notification = create_notification(template=sample_email_template, reply_to_text="test@test.com\t")

    send_to_providers.send_email_to_provider(db_notification)

    _, kwargs = mock_email_client.send_email.call_args
    assert kwargs['reply_to_address'] == "test@test.com"


def test_send_sms_to_provider_should_format_phone_number(sample_notification, mock_sms_client):
    sample_notification.to = '+1 650 253 2222'

    send_to_providers.send_sms_to_provider(sample_notification)

    # TODO: don't test the actual return value of notification_utils.recipients.validate_and_format_phone_number
    # instead, mock that dependency and check that it's used properly
    assert mock_sms_client.send_sms.call_args[1]['to'] == '+16502532222'


def test_send_email_to_provider_should_format_email_address(
        sample_email_notification,
        mock_email_client,
        mocked_build_ga_pixel_url
):
    sample_email_notification.to = 'test@example.com\t'

    send_to_providers.send_email_to_provider(sample_email_notification)

    _, kwargs = mock_email_client.send_email.call_args
    assert kwargs['to_addresses'] == 'test@example.com'


def test_notification_document_with_pdf_attachment(mocker, mock_email_client, sample_service_full_permissions):
    template = create_template(
        template_type='email',
        content='Here is your ((file))',
        service=sample_service_full_permissions
    )
    personalisation = {
        "file": {
            "file_name": "some_file.pdf",
            "sending_method": "attach",
            "id": str(uuid.uuid4()),
            "encryption_key": str(bytes(32))
        }
    }

    db_notification = create_notification(template=template, personalisation=personalisation)

    mock_attachment_store = mocker.Mock()
    mocker.patch('app.delivery.send_to_providers.attachment_store', new=mock_attachment_store)
    mock_attachment_store.get.return_value = 'request_content'.encode()

    send_to_providers.send_email_to_provider(db_notification)

    _, kwargs = mock_attachment_store.get.call_args
    assert kwargs == {
        'service_id': sample_service_full_permissions.id,
        'sending_method': personalisation["file"]["sending_method"],
        'attachment_id': personalisation["file"]["id"],
        'decryption_key': personalisation["file"]["encryption_key"],
    }
    attachments = [{'data': 'request_content'.encode(), 'name': "some_file.pdf"}]

    _, kwargs = mock_email_client.send_email.call_args
    assert kwargs['attachments'] == attachments

    assert Notification.query.get(db_notification.id).status == 'sending'


def test_notification_raises_error_if_message_contains_sin_pii_that_passes_luhn(
        sample_email_template_with_html,
        mocker,
        notify_api):
    send_mock = mocker.patch("app.aws_ses_client.send_email", return_value='reference')
    mocker.patch('app.googleanalytics.pixels.build_ga_pixel_url', return_value='url')

    db_notification = create_notification(
        template=sample_email_template_with_html,
        to_field="jo.smith@example.com",
        personalisation={'name': '046-454-286'}
    )

    with set_config_values(notify_api, {
        'SCAN_FOR_PII': "True",
    }):
        with pytest.raises(NotificationTechnicalFailureException) as e:
            send_to_providers.send_email_to_provider(db_notification)
            assert db_notification.id in e.value

    send_mock.assert_not_called()

    assert Notification.query.get(db_notification.id).status == 'pii-check-failed'


def test_notification_passes_if_message_contains_sin_pii_that_fails_luhn(
        sample_email_template_with_html,
        mock_email_client,
        mocked_build_ga_pixel_url
):
    db_notification = create_notification(
        template=sample_email_template_with_html,
        to_field="jo.smith@example.com",
        personalisation={'name': '123-456-789'}
    )

    send_to_providers.send_email_to_provider(db_notification)

    mock_email_client.send_email.assert_called()

    assert Notification.query.get(db_notification.id).status == 'sending'


def test_notification_passes_if_message_contains_phone_number(
        sample_email_template_with_html,
        mock_email_client,
        mocked_build_ga_pixel_url
):

    db_notification = create_notification(
        template=sample_email_template_with_html,
        to_field="jo.smith@example.com",
        personalisation={'name': '123-456-7890'}
    )

    send_to_providers.send_email_to_provider(db_notification)

    mock_email_client.send_email.assert_called()

    assert Notification.query.get(db_notification.id).status == 'sending'


def test_load_provider_throws_exception_if_provider_is_inactive(fake_uuid, mocker):
    mocker.patch(
        'app.delivery.send_to_providers.get_provider_details_by_id',
        return_value=mocker.Mock(ProviderDetails, active=False)
    )

    with pytest.raises(InvalidProviderException, match=f'^provider {fake_uuid} is not active$'):
        load_provider(fake_uuid)


def test_load_provider_throws_exception_if_provider_is_not_found(fake_uuid, mocker):
    mocker.patch(
        'app.delivery.send_to_providers.get_provider_details_by_id',
        return_value=None
    )

    with pytest.raises(InvalidProviderException, match=f'^provider {fake_uuid} could not be found'):
        load_provider(fake_uuid)


def test_load_provider_returns_provider_details_if_provider_is_active(fake_uuid, mocker):
    mocked_provider_details = mocker.Mock(ProviderDetails, active=True)

    mocker.patch(
        'app.delivery.send_to_providers.get_provider_details_by_id',
        return_value=mocked_provider_details
    )

    provider_details = load_provider(fake_uuid)
    assert provider_details == mocked_provider_details


def test_provider_to_use_should_return_template_provider(mocker):
    mocker.patch.dict(os.environ, {'TEMPLATE_SERVICE_PROVIDERS_ENABLED': 'True'})
    client_name = 'template-client'
    mocked_client = mocker.Mock(EmailClient)
    mocker.patch.object(mocked_client, 'get_name', return_value=client_name)

    mocked_template_provider_details = mocker.Mock(
        ProviderDetails,
        active=True,
        identifier=client_name
    )

    template_provider_id = uuid.uuid4()
    mocked_template = mocker.Mock(TemplateBase, provider_id=template_provider_id)

    mocked_notification = mocker.Mock(Notification, notification_type=EMAIL_TYPE, template=mocked_template)

    mocked_get_provider_details_by_id = mocker.patch(
        'app.delivery.send_to_providers.get_provider_details_by_id',
        return_value=mocked_template_provider_details
    )
    mocked_get_client_by_name_and_type = mocker.patch(
        'app.delivery.send_to_providers.clients.get_client_by_name_and_type',
        return_value=mocked_client
    )

    client = send_to_providers.provider_to_use(mocked_notification)

    mocked_get_provider_details_by_id.assert_called_once_with(template_provider_id)
    mocked_get_client_by_name_and_type.assert_called_once_with(client_name, EMAIL_TYPE)

    assert client == mocked_client


class TestProviderToUse:

    @staticmethod
    def mock_feature_flag(mocker, feature_flag: FeatureFlag, enabled: bool = True):
        mocker.patch.dict(os.environ, {feature_flag.value: str(enabled)})

    def test_uses_provider_service_if_enabled(self, mocker):
        self.mock_feature_flag(mocker, FeatureFlag.PROVIDER_STRATEGIES_ENABLED)

        mock_provider_service = mocker.Mock(ProviderService)
        mock_provider = mocker.Mock(ProviderDetails, identifier='some-identifier')
        mock_provider_service.get_provider.return_value = mock_provider
        mocker.patch('app.delivery.send_to_providers.provider_service', new=mock_provider_service)

        mocked_notification = mocker.Mock(
            Notification,
            notification_type=EMAIL_TYPE
        )

        mocked_client = mocker.Mock(EmailClient)
        mocked_get_client_by_name_and_type = mocker.patch(
            'app.delivery.send_to_providers.clients.get_client_by_name_and_type',
            return_value=mocked_client
        )

        client = send_to_providers.provider_to_use(mocked_notification)

        mock_provider_service.get_provider.assert_called_once_with(mocked_notification)
        mocked_get_client_by_name_and_type.assert_called_once_with(mock_provider.identifier, EMAIL_TYPE)

        assert client == mocked_client

    def test_returns_service_provider_if_template_has_no_provider(self, fake_uuid, mocker):
        self.mock_feature_flag(mocker, FeatureFlag.PROVIDER_STRATEGIES_ENABLED, False)
        self.mock_feature_flag(mocker, FeatureFlag.TEMPLATE_SERVICE_PROVIDERS_ENABLED)

        mocked_template = mocker.Mock(TemplateBase, provider_id=None)

        service_provider_id = uuid.uuid4()
        mocked_service = mocker.Mock(Service, email_provider_id=service_provider_id)

        mocked_notification = mocker.Mock(
            Notification,
            notification_type=EMAIL_TYPE,
            template=mocked_template,
            service=mocked_service
        )

        mock_provider_details = mocker.Mock(
            ProviderDetails,
            active=True,
            identifier='some-identifier'
        )
        mocked_get_provider_details_by_id = mocker.patch(
            'app.delivery.send_to_providers.get_provider_details_by_id',
            return_value=mock_provider_details
        )

        mocked_client = mocker.Mock(EmailClient)
        mocked_get_client_by_name_and_type = mocker.patch(
            'app.delivery.send_to_providers.clients.get_client_by_name_and_type',
            return_value=mocked_client
        )

        client = send_to_providers.provider_to_use(mocked_notification)

        mocked_get_provider_details_by_id.assert_called_once_with(service_provider_id)
        mocked_get_client_by_name_and_type.assert_called_once_with(mock_provider_details.identifier, EMAIL_TYPE)

        assert client == mocked_client

    def test_should_return_template_provider_if_template_and_service_have_providers(self, mocker):
        self.mock_feature_flag(mocker, FeatureFlag.PROVIDER_STRATEGIES_ENABLED, False)
        self.mock_feature_flag(mocker, FeatureFlag.TEMPLATE_SERVICE_PROVIDERS_ENABLED)

        template_provider_id = uuid.uuid4()
        mocked_template = mocker.Mock(TemplateBase, provider_id=template_provider_id)
        mocked_service = mocker.Mock(Service, email_provider_id=uuid.uuid4())

        mocked_notification = mocker.Mock(
            Notification,
            notification_type=EMAIL_TYPE,
            template=mocked_template,
            service=mocked_service
        )

        mock_provider_details = mocker.Mock(
            ProviderDetails,
            active=True,
            identifier='some-identifier'
        )
        mocked_get_provider_details_by_id = mocker.patch(
            'app.delivery.send_to_providers.get_provider_details_by_id',
            return_value=mock_provider_details
        )

        mocked_client = mocker.Mock(EmailClient)
        mocked_get_client_by_name_and_type = mocker.patch(
            'app.delivery.send_to_providers.clients.get_client_by_name_and_type',
            return_value=mocked_client
        )

        client = send_to_providers.provider_to_use(mocked_notification)

        mocked_get_provider_details_by_id.assert_called_once_with(template_provider_id)
        mocked_get_client_by_name_and_type.assert_called_once_with(mock_provider_details.identifier, EMAIL_TYPE)

        assert client == mocked_client

    def test_should_raise_exception_if_template_provider_is_inactive(self, mocker):
        self.mock_feature_flag(mocker, FeatureFlag.PROVIDER_STRATEGIES_ENABLED, False)
        self.mock_feature_flag(mocker, FeatureFlag.TEMPLATE_SERVICE_PROVIDERS_ENABLED)
        template_provider_id = uuid.uuid4()
        mocked_template_provider_details = mocker.Mock(
            ProviderDetails,
            active=False
        )

        mocked_template = mocker.Mock(TemplateBase, provider_id=template_provider_id)
        mocked_service = mocker.Mock(Service, email_provider_id=uuid.uuid4())

        mocked_notification = mocker.Mock(
            Notification,
            notification_type=EMAIL_TYPE,
            template=mocked_template,
            service=mocked_service
        )

        mocker.patch(
            'app.delivery.send_to_providers.get_provider_details_by_id',
            return_value=mocked_template_provider_details
        )

        mocked_get_client_by_name_and_type = mocker.patch(
            'app.delivery.send_to_providers.clients.get_client_by_name_and_type'
        )

        with pytest.raises(InvalidProviderException, match=f'^provider {str(template_provider_id)} is not active$'):
            send_to_providers.provider_to_use(mocked_notification)

        mocked_get_client_by_name_and_type.assert_not_called()

    def test_template_or_service_provider_is_not_used_when_feature_flag_is_off(self, mocker, fake_uuid):
        self.mock_feature_flag(mocker, FeatureFlag.PROVIDER_STRATEGIES_ENABLED, False)
        self.mock_feature_flag(mocker, FeatureFlag.TEMPLATE_SERVICE_PROVIDERS_ENABLED, False)
        mocked_client = mocker.Mock(EmailClient)

        mocker.patch(
            'app.delivery.send_to_providers.clients.get_client_by_name_and_type',
            return_value=mocked_client
        )

        mock_load_provider = mocker.patch(
            'app.delivery.send_to_providers.load_provider'
        )

        mocker.patch(
            'app.delivery.send_to_providers.get_provider_details_by_notification_type',
            return_value=[mocker.Mock(ProviderDetails, active=True)]
        )

        send_to_providers.provider_to_use(mocker.Mock(Notification))

        mock_load_provider.assert_not_called()
