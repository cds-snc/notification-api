import os
import uuid
from datetime import datetime
from unittest.mock import ANY

import pytest
from flask import current_app
from notifications_utils.recipients import ValidatedPhoneNumber
from requests import HTTPError
from sqlalchemy import select

import app
from app import aws_sns_client, mmg_client
from app.clients.email import EmailClient
from app.clients.sms import SmsClient
from app.constants import (
    EMAIL_TYPE,
    FIRETEXT_PROVIDER,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEST,
    KEY_TYPE_TEAM,
    MMG_PROVIDER,
    NOTIFICATION_CREATED,
    NOTIFICATION_SENDING,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_SENT,
    PINPOINT_PROVIDER,
    SERVICE_PERMISSION_TYPES,
    SES_PROVIDER,
    SMS_TYPE,
    TWILIO_PROVIDER,
)
from app.dao import notifications_dao
from app.delivery import send_to_providers
from app.exceptions import InactiveServiceException, InvalidProviderException
from app.models import (
    Notification,
    TemplateHistory,
)
from app.utils import get_html_email_options, get_logo_url
from tests.conftest import set_config_values


@pytest.fixture
def mock_source_email_address(mocker):
    source_email_address = '"Some Name" <some-user@some.domain>'
    mock_compute_function = mocker.patch(
        'app.delivery.send_to_providers.compute_source_email_address', return_value=source_email_address
    )
    return (source_email_address, mock_compute_function)


def test_should_send_personalised_template_to_correct_sms_provider_and_persist(
    notify_db_session, sample_api_key, sample_notification, sample_service, sample_template, mock_sms_client
):
    service = sample_service(prefix_sms=True)
    api_key = sample_api_key(service=service)
    template = sample_template(service=service, content='Hello (( Name))\nHere is <em>some HTML</em> & entities')

    db_notification = sample_notification(
        template=template,
        to_field='+16502532222',
        personalisation={'name': 'Jo'},
        status=NOTIFICATION_CREATED,
        reply_to_text=service.get_default_sms_sender(),
        api_key=api_key,
    )

    send_to_providers.send_sms_to_provider(db_notification)

    mock_sms_client.send_sms.assert_called_once_with(
        to=ValidatedPhoneNumber('+16502532222').formatted,
        content=f'{service.name}: Hello Jo\nHere is <em>some HTML</em> & entities',
        reference=str(db_notification.id),
        sender=current_app.config['FROM_NUMBER'],
        service_id=ANY,
        sms_sender_id=ANY,
        created_at=db_notification.created_at,
    )

    notification = notify_db_session.session.get(Notification, db_notification.id)

    assert notification.status == NOTIFICATION_SENDING
    assert notification.sent_at <= datetime.utcnow()
    assert notification.sent_by == mock_sms_client.get_name()
    assert notification.billable_units == 1
    assert notification.personalisation == {'name': 'Jo'}
    assert notification.reference == db_notification.reference


def test_send_email_to_provider_should_compute_source_email_address(
    sample_api_key,
    sample_notification,
    sample_template,
    mock_email_client,
    mock_source_email_address,
):
    template = sample_template(
        template_type=EMAIL_TYPE,
        subject='((name)) <em>some HTML</em>',
        content='Hello ((name))\nThis is an email from GOV.UK with <em>some HTML</em>',
    )
    db_notification = sample_notification(
        template=template,
        to_field='jo.smith@example.com',
        personalisation={'name': 'Jo'},
        api_key=sample_api_key(service=template.service),
    )
    mock_compute_email_from = mock_source_email_address[1]

    send_to_providers.send_email_to_provider(db_notification)

    mock_compute_email_from.assert_called_once_with(db_notification.service, mock_email_client)


@pytest.mark.parametrize('name_value', ['Jo', 'John Smith', 'Jane Doe-Smith'])
def test_should_send_personalised_template_to_correct_email_provider_and_persist(
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_template,
    mock_email_client,
    mocker,
    notify_api,
    mock_source_email_address,
    name_value,
):
    template = sample_template(
        template_type=EMAIL_TYPE,
        subject='((name)) <em>some HTML</em>',
        content='Hello ((name))\nThis is an email from VA with <em>some HTML</em>',
    )
    db_notification = sample_notification(
        template=template,
        to_field='jo.smith@example.com',
        personalisation={'name': name_value},
        api_key=sample_api_key(service=template.service),
    )

    mocker.patch.dict(os.environ, {'REVISED_TEMPLATE_RENDERING': 'False'})

    with set_config_values(notify_api, {'NOTIFY_EMAIL_FROM_NAME': 'Default Name'}):
        send_to_providers.send_email_to_provider(db_notification)

    mock_email_client.send_email.assert_called_once_with(
        source=mock_source_email_address[0],
        to_addresses='jo.smith@example.com',
        subject=f'{name_value} <em>some HTML</em>',
        body=f'Hello {name_value}\nThis is an email from VA with <em>some HTML</em>\n\n',
        html_body=ANY,
        reply_to_address=None,
        attachments=[],
    )

    assert '<!DOCTYPE html' in mock_email_client.send_email.call_args[1]['html_body']
    assert '&lt;em&gt;some HTML&lt;/em&gt;' in mock_email_client.send_email.call_args[1]['html_body']
    assert (
        f'Hello {name_value}<br />\nThis is an email from VA with <em>some HTML</em>'
        in mock_email_client.send_email.call_args[1]['html_body']
    )

    stmt = select(Notification).where(Notification.id == db_notification.id)
    notification = notify_db_session.session.scalars(stmt).one()

    assert notification.status == NOTIFICATION_SENDING
    assert notification.sent_at <= datetime.utcnow()
    assert notification.sent_by == mock_email_client.get_name()
    assert notification.personalisation == {'name': name_value}


def test_should_not_send_email_message_when_service_is_inactive_notification_is_not_updated(
    notify_db_session,
    sample_api_key,
    sample_template,
    sample_notification,
    mock_email_client,
):
    template = sample_template()
    template.service.active = False
    api_key = sample_api_key(service=template.service)
    notification = sample_notification(template=template, api_key=api_key)

    with pytest.raises(InactiveServiceException) as e:
        send_to_providers.send_email_to_provider(notification)
    assert str(notification.id) in str(e.value)
    mock_email_client.send_email.assert_not_called()
    # notification is not updated until the exception is caught by "deliver_email"
    assert notify_db_session.session.get(Notification, notification.id).status == NOTIFICATION_CREATED


@pytest.mark.parametrize('client_send', ['app.aws_sns_client.send_sms', 'app.mmg_client.send_sms'])
def test_should_not_send_sms_message_when_service_is_inactive_notifcation_is_not_updated(
    notify_db_session,
    sample_api_key,
    sample_template,
    sample_notification,
    mocker,
    client_send,
):
    template = sample_template()
    template.service.active = False
    api_key = sample_api_key(service=template.service)
    notification = sample_notification(template=template, api_key=api_key)
    send_mock = mocker.patch(client_send, return_value='reference')

    with pytest.raises(InactiveServiceException) as e:
        send_to_providers.send_sms_to_provider(notification)
    assert str(notification.id) in str(e.value)
    send_mock.assert_not_called()
    # notification is not updated until the exception is caught by "deliver_sms" or "deliver_sms_with_rate_limiting"
    assert notify_db_session.session.get(Notification, notification.id).status == NOTIFICATION_CREATED


@pytest.mark.parametrize('prefix', [True, False])
def test_send_sms_should_use_template_version_from_notification_not_latest(
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_provider,
    sample_service,
    sample_template,
    mock_sms_client,
    prefix,
):
    sample_provider()
    service = sample_service(prefix_sms=prefix)
    template = sample_template(service=service)

    db_notification = sample_notification(
        template=template,
        to_field='+16502532222',
        status=NOTIFICATION_CREATED,
        reply_to_text=service.get_default_sms_sender(),
        api_key=sample_api_key(service=template.service),
    )

    version_on_notification = template.version

    # Change the template and ensure it uses the version associated with the notification
    from app.dao.templates_dao import dao_update_template, dao_get_template_by_id

    template.content = template.content + ' another version of the template'
    dao_update_template(template)
    t = dao_get_template_by_id(template.id)
    assert t.version > version_on_notification

    send_to_providers.send_sms_to_provider(db_notification)
    stmt = (
        select(TemplateHistory)
        .where(TemplateHistory.id == db_notification.template_id)
        .where(TemplateHistory.version == db_notification.template_version)
    )
    content = notify_db_session.session.scalar(stmt).content

    mock_sms_client.send_sms.assert_called_once_with(
        to=ValidatedPhoneNumber('+16502532222').formatted,
        content=content if not prefix else f'{service.name}: {content}',
        reference=str(db_notification.id),
        sender=current_app.config['FROM_NUMBER'],
        service_id=ANY,
        sms_sender_id=ANY,
        created_at=db_notification.created_at,
    )

    persisted_notification = notifications_dao.get_notification_by_id(db_notification.id)
    assert persisted_notification.to == db_notification.to
    assert persisted_notification.template_id == template.id
    assert persisted_notification.template_version == version_on_notification
    assert persisted_notification.template_version != template.version
    assert persisted_notification.status == NOTIFICATION_SENDING
    assert not persisted_notification.personalisation


@pytest.mark.parametrize('research_mode,key_type', [(True, KEY_TYPE_NORMAL), (False, KEY_TYPE_TEST)])
def test_should_call_send_sms_response_task_if_research_mode(
    sample_api_key,
    sample_service,
    sample_notification,
    sample_template,
    mocker,
    mock_sms_client,
    research_mode,
    key_type,
):
    mocker.patch('app.delivery.send_to_providers.send_sms_response')

    if research_mode:
        service = sample_service(research_mode=True)
    else:
        service = sample_service()

    api_key = sample_api_key(service=service, key_type=key_type)
    template = sample_template(service=api_key.service)
    notification = sample_notification(template=template, api_key=api_key)
    # sample_notification.reference = None

    send_to_providers.send_sms_to_provider(notification)
    assert not mock_sms_client.send_sms.called

    app.delivery.send_to_providers.send_sms_response.assert_called_once_with(
        mock_sms_client.get_name(), str(notification.id), notification.to, notification.reference
    )

    persisted_notification = notifications_dao.get_notification_by_id(notification.id)
    assert persisted_notification.to == notification.to
    assert persisted_notification.template_id == notification.template_id
    assert persisted_notification.status == NOTIFICATION_SENDING
    assert persisted_notification.sent_at <= datetime.utcnow()
    assert persisted_notification.sent_by == mock_sms_client.get_name()
    assert persisted_notification.reference
    assert not persisted_notification.personalisation


def test_should_have_sent_status_if_fake_callback_function_fails(
    sample_api_key,
    sample_notification,
    sample_template,
    mocker,
    mock_sms_client,
):
    mocker.patch('app.delivery.send_to_providers.send_sms_response', side_effect=HTTPError)
    template = sample_template()
    api_key = sample_api_key(service=template.service, key_type=KEY_TYPE_TEST)
    notification = sample_notification(template=template, api_key=api_key)

    with pytest.raises(HTTPError):
        send_to_providers.send_sms_to_provider(notification)
    assert notification.status == NOTIFICATION_SENDING
    assert notification.sent_by == mock_sms_client.get_name()


def test_should_not_send_to_provider_when_status_is_not_created(
    sample_api_key,
    sample_notification,
    sample_template,
    mocker,
):
    template = sample_template()
    api_key = sample_api_key(service=template.service)
    notification = sample_notification(template=template, status=NOTIFICATION_SENDING, api_key=api_key)
    mocker.patch('app.aws_sns_client.send_sms')
    response_mock = mocker.patch('app.delivery.send_to_providers.send_sms_response')

    send_to_providers.send_sms_to_provider(notification)

    app.aws_sns_client.send_sms.assert_not_called()
    response_mock.assert_not_called()


def test_should_send_sms_with_downgraded_content(
    sample_api_key,
    sample_notification,
    sample_service,
    sample_template,
    mock_sms_client,
):
    # é, o, and u are in GSM.
    # á, ï, grapes, tabs, zero width space and ellipsis are not
    msg = 'á é ï o u 🍇 foo\tbar\u200bbaz((misc))…'
    placeholder = '∆∆∆abc'
    gsm_message = '?odz Housing Service: a é i o u ? foo barbaz???abc...'
    service = sample_service(service_name='Łódź Housing Service', prefix_sms=True)
    template = sample_template(service=service, content=msg)
    db_notification = sample_notification(
        template=template,
        personalisation={'misc': placeholder},
        api_key=sample_api_key(service=service),
    )

    send_to_providers.send_sms_to_provider(db_notification)

    mock_sms_client.send_sms.assert_called_once_with(
        to=ANY,
        content=gsm_message,
        reference=ANY,
        sender=ANY,
        service_id=ANY,
        sms_sender_id=ANY,
        created_at=db_notification.created_at,
    )


def test_send_sms_should_use_service_sms_sender(
    sample_api_key,
    sample_notification,
    sample_sms_sender,
    sample_template,
    mock_sms_client,
):
    template = sample_template()
    api_key = sample_api_key(service=template.service)
    sms_sender = sample_sms_sender(service_id=template.service.id, sms_sender='123456', is_default=False)
    db_notification = sample_notification(template=template, reply_to_text=sms_sender.sms_sender, api_key=api_key)

    send_to_providers.send_sms_to_provider(
        db_notification,
    )

    mock_sms_client.send_sms.assert_called_once_with(
        to=ANY,
        content=ANY,
        reference=ANY,
        sender=sms_sender.sms_sender,
        service_id=ANY,
        sms_sender_id=ANY,
        created_at=db_notification.created_at,
    )


@pytest.mark.parametrize('research_mode,key_type', [(True, KEY_TYPE_NORMAL), (False, KEY_TYPE_TEST)])
def test_send_email_to_provider_should_call_research_mode_task_response_task_if_research_mode(
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_template,
    mocker,
    mock_email_client,
    research_mode,
    key_type,
):
    reference = str(uuid.uuid4())
    template = sample_template(template_type=EMAIL_TYPE)
    api_key = sample_api_key(service=template.service, key_type=key_type)
    notification = sample_notification(
        template=template,
        to_field=f'{reference}john@smith.com',
        api_key=api_key,
        billable_units=0,
    )
    template.service.research_mode = research_mode

    mocker.patch('app.delivery.send_to_providers.send_email_response')

    send_to_providers.send_email_to_provider(notification)

    assert not mock_email_client.send_email.called
    research_ref = app.delivery.send_to_providers.send_email_response.call_args[0][0]
    assert research_ref != reference
    persisted_notification = notify_db_session.session.get(Notification, notification.id)
    assert persisted_notification.to == f'{reference}john@smith.com'
    assert persisted_notification.template_id == template.id
    assert persisted_notification.status == NOTIFICATION_SENDING
    assert persisted_notification.sent_at <= datetime.utcnow()
    assert persisted_notification.created_at <= datetime.utcnow()
    assert persisted_notification.sent_by == mock_email_client.get_name()
    assert persisted_notification.reference == research_ref
    assert persisted_notification.billable_units == 0


def test_send_email_to_provider_should_not_send_to_provider_when_status_is_not_created(
    sample_api_key,
    sample_notification,
    sample_template,
    mocker,
):
    template = sample_template(template_type=EMAIL_TYPE)
    api_key = sample_api_key(service=template.service)
    notification = sample_notification(template=template, status=NOTIFICATION_SENDING, api_key=api_key)
    mocker.patch('app.aws_ses_client.send_email')
    mocker.patch('app.delivery.send_to_providers.send_email_response')

    send_to_providers.send_sms_to_provider(notification)
    app.aws_ses_client.send_email.assert_not_called()
    app.delivery.send_to_providers.send_email_response.assert_not_called()


def test_send_email_should_use_service_reply_to_email(
    sample_api_key,
    sample_notification,
    sample_provider,
    sample_template,
    mock_email_client,
):
    sample_provider(identifier=SES_PROVIDER, notification_type=EMAIL_TYPE)
    template = sample_template(template_type=EMAIL_TYPE)

    db_notification = sample_notification(
        template=template,
        api_key=sample_api_key(service=template.service),
        reply_to_text=template.service.email_from,
    )

    send_to_providers.send_email_to_provider(db_notification)

    _, kwargs = mock_email_client.send_email.call_args
    assert kwargs['reply_to_address'] == template.service.email_from


def test_get_html_email_renderer_should_return_for_normal_service(
    notify_api,
    sample_notification_model_with_organization,
):
    options = get_html_email_options(sample_notification_model_with_organization)
    assert options['default_banner'] is True


def test_get_html_email_renderer_with_branding_details_and_render_default_banner_only(
    notify_api,
    sample_notification_model_with_organization,
):
    sample_notification_model_with_organization.service.email_branding = None

    options = get_html_email_options(sample_notification_model_with_organization)

    assert {'default_banner': True, 'brand_banner': False}.items() <= options.items()


@pytest.mark.parametrize(
    'base_url, expected_url',
    [
        # don't change localhost to prevent errors when testing locally
        ('http://localhost:6012', 'filename.png'),
        ('https://www.notifications.service.gov.uk', 'filename.png'),
    ],
)
def test_get_logo_url_works_for_different_environments(
    base_url,
    client,
    expected_url,
):
    logo_file = 'filename.png'

    logo_url = get_logo_url(base_url, logo_file)
    domain = 'dev-notifications-va-gov-assets.s3.amazonaws.com'
    assert logo_url == 'https://{}/{}'.format(domain, expected_url)


@pytest.mark.skip(reason='#2463 - This test passes but causes teardown errors.')
def test_should_not_update_notification_on_exception_if_research_mode(
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_provider,
    sample_service,
    sample_template,
    mocker,
):
    """
    In research mode, don't update a notification's status to "sending" if an
    exception occurs during the request to the provider.
    """

    provider = sample_provider()
    assert provider.identifier == PINPOINT_PROVIDER
    service = sample_service(research_mode=True, sms_provider_id=str(provider.id))
    template = sample_template(service=service)

    notification = sample_notification(
        template=template,
        api_key=sample_api_key(service),
        billable_units=0,
    )
    assert notification.key_type != KEY_TYPE_TEST
    assert notification.billable_units == 0
    assert notification.notification_type == provider.notification_type

    mocker.patch('app.delivery.send_to_providers.send_sms_response', side_effect=Exception())

    with pytest.raises(Exception):
        send_to_providers.send_sms_to_provider(notification)

    notify_db_session.session.refresh(notification)
    assert notification.billable_units == 0


def __update_notification(notification_to_update, research_mode, expected_status):
    if research_mode or notification_to_update.key_type == KEY_TYPE_TEST:
        notification_to_update.status = expected_status


@pytest.mark.parametrize(
    'research_mode,key_type, billable_units, expected_status',
    [
        (True, KEY_TYPE_NORMAL, 0, NOTIFICATION_DELIVERED),
        (False, KEY_TYPE_NORMAL, 1, NOTIFICATION_SENDING),
        (False, KEY_TYPE_TEST, 0, NOTIFICATION_SENDING),
        (True, KEY_TYPE_TEST, 0, NOTIFICATION_SENDING),
        (True, KEY_TYPE_TEAM, 0, NOTIFICATION_DELIVERED),
        (False, KEY_TYPE_TEAM, 1, NOTIFICATION_SENDING),
    ],
)
def test_should_update_billable_units_and_status_according_to_research_mode_and_key_type(
    sample_api_key,
    sample_notification,
    sample_template,
    mocker,
    mock_sms_client,  # Required because there's no client/provider
    research_mode,
    key_type,
    billable_units,
    expected_status,
):
    template = sample_template()
    api_key = sample_api_key(service=template.service, key_type=key_type)
    notification = sample_notification(
        template=template, billable_units=0, status=NOTIFICATION_CREATED, api_key=api_key
    )
    mocker.patch(
        'app.delivery.send_to_providers.send_sms_response',
        side_effect=__update_notification(notification, research_mode, expected_status),
    )

    if research_mode:
        template.service.research_mode = True

    send_to_providers.send_sms_to_provider(notification)
    assert notification.billable_units == billable_units
    assert notification.status == expected_status


def test_should_set_notification_billable_units_if_sending_to_provider_fails(
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_provider,
    sample_template,
    mocker,
):
    mocker.patch('app.aws_pinpoint_client.send_sms', side_effect=HTTPError())

    provider = sample_provider()
    template = sample_template(provider_id=str(provider.id))
    notification = sample_notification(
        template=template,
        api_key=sample_api_key(service=template.service),
        billable_units=0,
    )
    assert notification.sent_by is None

    with pytest.raises(HTTPError):
        send_to_providers.send_sms_to_provider(notification)

    notify_db_session.session.refresh(notification)
    assert notification.billable_units == 1


@pytest.mark.skip(reason='Currently not supporting international providers')
def test_should_send_sms_to_international_providers(
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_provider,
    sample_service,
    sample_template,
    sample_user,
    mocker,
):
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=sample_user())
    sample_provider(identifier=FIRETEXT_PROVIDER, supports_international=True)
    sample_provider(identifier=MMG_PROVIDER, supports_international=True)

    # TODO - Changes for #2249 deleted this function because it isn't used in the application.  If this
    # test is unskipped, it will need to be refactored.
    # dao_switch_sms_provider_to_provider_with_identifier(FIRETEXT_PROVIDER)

    service = sample_service(prefix_sms=True)
    template = sample_template(service=service, content='Hello (( Name))\nHere is <em>some HTML</em> & entities')
    api_key = sample_api_key(service=service)
    db_notification = sample_notification(
        template=template,
        to_field='+16135555555',
        personalisation={'name': 'Jo'},
        status=NOTIFICATION_CREATED,
        international=False,
        reply_to_text=service.get_default_sms_sender(),
        api_key=api_key,
    )

    db_notification_int = sample_notification(
        template=template,
        to_field='+1613555555',
        personalisation={'name': 'Jo'},
        status=NOTIFICATION_CREATED,
        international=False,
        reply_to_text=service.get_default_sms_sender(),
        api_key=api_key,
    )

    mocker.patch('app.aws_sns_client.send_sms')
    mocker.patch('app.mmg_client.send_sms')

    send_to_providers.send_sms_to_provider(db_notification)

    mmg_client.send_sms.assert_called_once_with(
        to='16135555555',
        content=ANY,
        reference=str(db_notification.id),
        sender=current_app.config['FROM_NUMBER'],
        sms_sender_id=ANY,
    )

    send_to_providers.send_sms_to_provider(db_notification_int)

    aws_sns_client.send_sms.assert_called_once_with(
        to='601117224412',
        content=ANY,
        reference=str(db_notification_int.id),
        sender=current_app.config['FROM_NUMBER'],
        sms_sender_id=ANY,
    )

    notification = notify_db_session.session.get(Notification, db_notification.id)
    notification_int = notify_db_session.session.get(Notification, db_notification_int.id)

    assert notification.status == NOTIFICATION_SENDING
    assert notification.sent_by == FIRETEXT_PROVIDER
    assert notification_int.status == NOTIFICATION_SENT
    assert notification_int.sent_by == MMG_PROVIDER


@pytest.mark.parametrize(
    'sms_sender, expected_sender, prefix_sms, expected_content',
    [
        ('foo', 'foo', False, 'bar'),
        ('foo', 'foo', True, 'bar'),
        # if 40604 is actually in DB then treat that as if entered manually
        ('40604', '40604', False, 'bar'),
        # 'testing' is the FROM_NUMBER during unit tests
        ('testing', 'testing', True, 'bar'),
        ('testing', 'testing', False, 'bar'),
    ],
)
def test_should_handle_sms_sender_and_prefix_message(
    mock_sms_client,
    sms_sender,
    prefix_sms,
    expected_sender,
    expected_content,
    sample_api_key,
    sample_notification,
    sample_provider,
    sample_service,
    sample_template,
):
    sample_provider()
    service = sample_service(sms_sender=sms_sender, prefix_sms=prefix_sms)
    template = sample_template(service=service, content='bar')
    notification = sample_notification(
        template=template, reply_to_text=sms_sender, api_key=sample_api_key(service=template.service)
    )

    send_to_providers.send_sms_to_provider(notification, service.get_default_sms_sender_id())

    mock_sms_client.send_sms.assert_called_once_with(
        # Expecting the service name with a colon to prefix the content
        content=f'{service.name}: bar' if prefix_sms else expected_content,
        sender=expected_sender,
        to=ANY,
        reference=ANY,
        service_id=ANY,
        sms_sender_id=ANY,
        created_at=notification.created_at,
    )


def test_send_email_to_provider_uses_reply_to_from_notification(
    sample_api_key,
    sample_notification,
    sample_template,
    mock_email_client,
):
    template = sample_template(template_type=EMAIL_TYPE)
    db_notification = sample_notification(
        template=template, reply_to_text='test@test.com', api_key=sample_api_key(service=template.service)
    )

    send_to_providers.send_email_to_provider(db_notification)

    _, kwargs = mock_email_client.send_email.call_args
    assert kwargs['reply_to_address'] == 'test@test.com'


def test_send_email_to_provider_should_format_reply_to_email_address(
    sample_api_key,
    sample_notification,
    sample_provider,
    sample_template,
    mock_email_client,
):
    sample_provider(identifier=SES_PROVIDER, notification_type=EMAIL_TYPE)
    template = sample_template(template_type=EMAIL_TYPE)
    db_notification = sample_notification(
        template=template, reply_to_text='test@test.com\t', api_key=sample_api_key(service=template.service)
    )

    send_to_providers.send_email_to_provider(db_notification)

    _, kwargs = mock_email_client.send_email.call_args
    assert kwargs['reply_to_address'] == 'test@test.com'


def test_send_email_to_provider_should_not_trigger_second_email(
    sample_api_key,
    sample_notification,
    sample_provider,
    sample_template,
    mock_email_client,
):
    sample_provider(identifier=SES_PROVIDER, notification_type=EMAIL_TYPE)
    template = sample_template(template_type=EMAIL_TYPE)
    db_notification = sample_notification(template=template, api_key=sample_api_key(service=template.service))

    send_to_providers.send_email_to_provider(db_notification)
    # Second call should raise raise the runtime error
    with pytest.raises(RuntimeError):
        send_to_providers.send_email_to_provider(db_notification)


def test_send_sms_to_provider_should_format_phone_number(
    sample_api_key,
    sample_notification,
    sample_provider,
    sample_template,
    mock_sms_client,
):
    sample_provider()
    template = sample_template()
    api_key = sample_api_key(service=template.service)
    notification = sample_notification(template=template, api_key=api_key, to_field='+1 650 253 2222')

    send_to_providers.send_sms_to_provider(notification)
    assert mock_sms_client.send_sms.call_args[1]['to'] == '+16502532222'


def test_send_email_to_provider_should_format_email_address(
    sample_notification,
    mock_email_client,
):
    notification = sample_notification(to_field='test@example.com\t')

    send_to_providers.send_email_to_provider(notification)

    _, kwargs = mock_email_client.send_email.call_args
    assert kwargs['to_addresses'] == 'test@example.com'


def test_notification_document_with_pdf_attachment(
    mocker,
    mock_email_client,
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_provider,
    sample_service,
    sample_template,
):
    sample_provider()
    service = sample_service(
        service_name=f'sample service full permissions {uuid.uuid4()}', service_permissions=SERVICE_PERMISSION_TYPES
    )
    template = sample_template(template_type=EMAIL_TYPE, content='Here is your ((file))', service=service)
    api_key = sample_api_key(
        service=service,
    )
    personalisation = {
        'file': {
            'file_name': 'some_file.pdf',
            'sending_method': 'attach',
            'id': str(uuid.uuid4()),
            'encryption_key': str(bytes(32)),
        }
    }

    db_notification = sample_notification(template=template, personalisation=personalisation, api_key=api_key)

    mock_attachment_store = mocker.Mock()
    mocker.patch('app.delivery.send_to_providers.attachment_store', new=mock_attachment_store)
    mock_attachment_store.get.return_value = 'request_content'.encode()

    send_to_providers.send_email_to_provider(db_notification)

    _, kwargs = mock_attachment_store.get.call_args
    assert kwargs == {
        'service_id': service.id,
        'sending_method': personalisation['file']['sending_method'],
        'attachment_id': personalisation['file']['id'],
        'decryption_key': personalisation['file']['encryption_key'],
    }
    attachments = [{'data': 'request_content'.encode(), 'name': 'some_file.pdf'}]

    _, kwargs = mock_email_client.send_email.call_args
    assert kwargs['attachments'] == attachments

    assert notify_db_session.session.get(Notification, db_notification.id).status == NOTIFICATION_SENDING


def test_notification_passes_if_message_contains_phone_number(
    notify_db_session,
    sample_api_key,
    sample_notification,
    sample_provider,
    sample_template,
    mock_email_client,
):
    sample_provider(identifier=SES_PROVIDER, notification_type=EMAIL_TYPE)
    template = sample_template(
        template_type=EMAIL_TYPE,
        subject='((name)) <em>some HTML</em>',
        content='Hello ((name))\nThis is an email from va.gov with <em>some HTML</em>',
    )
    db_notification = sample_notification(
        template=template,
        to_field=f'{uuid.uuid4()}jo.smith@example.com',
        personalisation={'name': '123-456-7890'},
        api_key=sample_api_key(service=template.service),
    )

    send_to_providers.send_email_to_provider(db_notification)

    mock_email_client.send_email.assert_called()

    assert notify_db_session.session.get(Notification, db_notification.id).status == NOTIFICATION_SENDING


@pytest.mark.parametrize('client_type', [EMAIL_TYPE, SMS_TYPE])
def test_client_to_use_should_return_template_provider(
    notify_api,
    mocker,
    sample_provider,
    sample_template,
    sample_notification,
    client_type,
):
    # Client setup
    client_name = f'client_to_use_{client_type}'
    mocked_client = mocker.Mock(EmailClient) if client_type == EMAIL_TYPE else mocker.Mock(SmsClient)
    mocker.patch.object(mocked_client, 'get_name', return_value=client_name)
    mock_client_by_name = mocker.patch(
        'app.delivery.send_to_providers.clients.get_client_by_name_and_type',
        return_value=mocked_client,
    )

    # Sample object setup
    provider = sample_provider(client_name, notification_type=client_type, load_balancing_weight=9999)
    template = sample_template(template_type=client_type)

    # This must be specified because workers (may be the wrong provider otherwise)
    if client_type == EMAIL_TYPE:
        template.service.email_provider_id = provider.id
    else:
        template.service.sms_provider_id = provider.id
    notification = sample_notification(template=template)

    client = send_to_providers.client_to_use(notification)

    assert mock_client_by_name.called_with(provider.identifier, client_type)
    assert client == mocked_client


def test_returns_service_provider_if_template_has_no_provider(
    notify_api,
    sample_provider,
    sample_service,
    sample_template,
    sample_notification,
):
    provider = sample_provider()
    assert provider.identifier == PINPOINT_PROVIDER
    service = sample_service(sms_provider_id=str(provider.id))
    template = sample_template(service=service)
    assert template.provider_id is None
    notification = sample_notification(template=template)

    client = send_to_providers.client_to_use(notification)
    assert client.name == PINPOINT_PROVIDER


def test_should_return_template_provider_if_template_and_service_have_providers(
    notify_api,
    sample_provider,
    sample_service,
    sample_template,
    sample_notification,
):
    service_provider = sample_provider()
    assert service_provider.identifier == PINPOINT_PROVIDER
    service = sample_service(sms_provider_id=str(service_provider.id))

    template_provider = sample_provider(identifier=TWILIO_PROVIDER)
    assert template_provider.identifier == TWILIO_PROVIDER
    template = sample_template(service=service, provider_id=str(template_provider.id))

    notification = sample_notification(template=template)

    client = send_to_providers.client_to_use(notification)
    assert client.name == TWILIO_PROVIDER


def test_should_raise_exception_if_template_provider_is_inactive(
    notify_api,
    sample_provider,
    sample_template,
    sample_notification,
):
    provider = sample_provider(active=False)
    template = sample_template(provider_id=str(provider.id))
    notification = sample_notification(template=template)

    with pytest.raises(InvalidProviderException, match=f'provider {provider.display_name} is not active'):
        send_to_providers.client_to_use(notification)


@pytest.mark.parametrize('store_template_content_ff', [True, False])
def test_send_email_to_provider_includes_ga4_pixel_tracking_in_html_content(
    sample_api_key,
    sample_notification,
    sample_template,
    mock_email_client,
    notify_api,
    mocker,
    store_template_content_ff,
):
    """
    Test that emails sent through send_email_to_provider include a GA4 pixel tracking image in the HTML content
    when the feature flag is enabled.
    """

    # Create test data
    template = sample_template(
        template_type=EMAIL_TYPE,
        subject='Test Subject',
        content='Test Content',
    )

    db_notification = sample_notification(
        template=template,
        to_field='test@example.com',
        api_key=sample_api_key(service=template.service),
    )

    # Set up mocks
    pixel_url = f'https://test-api.va.gov/vanotify/ga4/open-email-tracking/{db_notification.id}'
    mocker.patch('app.dao.templates_dao.is_feature_enabled', return_value=store_template_content_ff)
    mocker.patch('app.googleanalytics.pixels.build_dynamic_ga4_pixel_tracking_url', return_value=pixel_url)

    send_to_providers.send_email_to_provider(db_notification)

    mock_email_client.send_email.assert_called_once()
    html_body = mock_email_client.send_email.call_args[1]['html_body']

    # Check for the GA4 pixel tracking image in the HTML content, regardless of the STORE_TEMPLATE_CONTENT feature flag
    expected_pixel_img = f'<img id="ga4_open_email_event_url" src="{pixel_url}"'
    assert expected_pixel_img in html_body, (
        f'GA4 pixel tracking image not found in HTML when feature enabled: {html_body}'
    )


@pytest.mark.parametrize('store_content_flag', [True, False])
def test_send_email_to_provider_html_body_is_always_string_type(
    sample_api_key,
    sample_notification,
    sample_template,
    mock_email_client,
    mocker,
    store_content_flag,
):
    """
    Ensure the html_body parameter passed to send_email is always a string regardless of the template content
    or feature flags.
    """

    template = sample_template(
        template_type=EMAIL_TYPE,
        subject='Test Subject',
        content='Test Content with ((placeholder))',
    )

    # Create notification with complex personalisation
    db_notification = sample_notification(
        template=template,
        to_field='test@example.com',
        personalisation={'placeholder': 'value with special chars: <>&"\''},
        api_key=sample_api_key(service=template.service),
    )

    # Set up feature flag
    mocker.patch('app.delivery.send_to_providers.is_feature_enabled', return_value=store_content_flag)
    mocker.patch('app.dao.templates_dao.is_feature_enabled', return_value=store_content_flag)
    mocker.patch('app.models.is_feature_enabled', return_value=store_content_flag)

    # Call the function under test
    send_to_providers.send_email_to_provider(db_notification)

    # Verify the call
    mock_email_client.send_email.assert_called_once()
    html_body = mock_email_client.send_email.call_args[1]['html_body']

    # Check that html_body is actually a string
    assert isinstance(html_body, str), f'html_body should be a string, got {type(html_body)} instead'

    # Ensure html_body has content (not empty)
    assert html_body, 'html_body should not be empty'
