from datetime import datetime, timedelta, timezone
import json
import os
from random import randint, randrange
from typing import List, Union
from uuid import UUID, uuid4

import boto3
import pytest
import pytz
import requests_mock
from moto import mock_aws

from app import db
from app.clients.email import EmailClient
from app.clients.sms import SmsClient
from app.clients.sms.firetext import FiretextClient
from app.constants import (
    DEFAULT_SERVICE_MANAGEMENT_PERMISSIONS,
    DEFAULT_SERVICE_NOTIFICATION_PERMISSIONS,
    DELIVERY_STATUS_CALLBACK_TYPE,
    EMAIL_TYPE,
    JOB_STATUS_SCHEDULED,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEST,
    KEY_TYPE_TEAM,
    LETTER_TYPE,
    MMG_PROVIDER,
    MOBILE_TYPE,
    NOTIFICATION_STATUS_TYPES,
    PINPOINT_PROVIDER,
    SMS_TYPE,
    TEMPLATE_PROCESS_NORMAL,
    WEBHOOK_CHANNEL_TYPE,
)
from app.dao.invited_user_dao import save_invited_user
from app.dao.organisation_dao import dao_create_organisation, dao_add_service_to_organisation
from app.dao.service_data_retention_dao import insert_service_data_retention
from app.dao.service_sms_sender_dao import (
    dao_update_service_sms_sender,
)
from app.dao.users_dao import create_secret_code, create_user_code
from app.dao.login_event_dao import save_login_event
from app.dao.templates_dao import dao_create_template
from app.model import IdentityProviderIdentifier, User
from app.models import (
    ApiKey,
    AnnualBilling,
    Complaint,
    CommunicationItem,
    Domain,
    EmailBranding,
    FactBilling,
    FactNotificationStatus,
    InboundNumber,
    InboundSms,
    InvitedOrganisationUser,
    InvitedUser,
    Job,
    LetterRate,
    LoginEvent,
    Notification,
    NotificationHistory,
    Organisation,
    Permission,
    ProviderDetails,
    ProviderDetailsHistory,
    ProviderRates,
    Rate,
    RecipientIdentifier,
    ScheduledNotification,
    ServiceCallback,
    ServiceDataRetention,
    ServiceEmailReplyTo,
    ServiceLetterContact,
    ServicePermission,
    ServiceSmsSender,
    Service,
    ServiceUser,
    ServiceWhitelist,
    Template,
    TemplateFolder,
    TemplateHistory,
    TemplateRedacted,
    template_folder_map,
    user_folder_permissions,
    user_to_organisation,
    UserServiceRoles,
)
from app.va.va_profile import VAProfileClient

from flask import current_app, url_for
from sqlalchemy import delete, update, select, Table
from sqlalchemy.orm import scoped_session
from sqlalchemy.orm.session import make_transient
from tests import create_admin_authorization_header
from tests.app.db import (
    create_api_key,
    create_job,
    create_notification,
    create_service,
    create_user,
    version_api_key,
    version_service,
)


# Tests only run against email/sms. API also considers letters
RESTRICTED_TEMPLATE_TYPES = [SMS_TYPE, EMAIL_TYPE]
MOCK_VA_PROFILE_URL = 'http://mock.vaprofile.va.gov'


def json_compare(a, b) -> bool:
    """
    Orders json elements recursively then compares them
    """
    return _ordered(a) == _ordered(b)


def _ordered(json_obj):
    """
    Recursively order the JSON object
    """
    if isinstance(json_obj, dict):
        return sorted((k, _ordered(v)) for k, v in json_obj.items())
    if isinstance(json_obj, list):
        return sorted(_ordered(x) for x in json_obj)
    else:
        return json_obj


@pytest.yield_fixture
def rmock():
    with requests_mock.mock() as rmock:
        yield rmock


@pytest.fixture
def set_user_as_admin(notify_db_session):
    def _wrapper(user: User) -> User:
        stmt = update(User).where(User.id == user.id).values(platform_admin=True)
        notify_db_session.session.execute(stmt)
        return notify_db_session.session.get(User, user.id)

    return _wrapper


@pytest.fixture
def sample_user(notify_db_session, set_user_as_admin):
    created_user_ids = []

    def _wrapper(
        blocked=False,
        check_if_user_exists=False,
        email=None,
        identity_provider_user_id=None,
        idp_id=None,
        idp_name=None,
        mobile_number='+16502532222',
        name='Test User',
        platform_admin=False,
        state='active',
        user_id=None,
    ):
        # Cannot set platform admin when creating a user (schema)
        user = create_user(
            blocked=blocked,
            check_if_user_exists=check_if_user_exists,
            email=email,
            identity_provider_user_id=identity_provider_user_id,
            idp_id=idp_id,
            idp_name=idp_name,
            mobile_number=mobile_number,
            name=name,
            state=state,
            user_id=user_id,
        )
        if platform_admin:
            user = set_user_as_admin(user)

        created_user_ids.append(user.id)

        return user

    yield _wrapper

    # Teardown
    user_cleanup(created_user_ids, notify_db_session.session)


def user_cleanup(user_ids: List[int], session: scoped_session, commit: bool = True):
    # Clear user_folder_permissions
    session.execute(delete(user_folder_permissions).where(user_folder_permissions.c.user_id.in_(user_ids)))

    # Clear IdentityProviderIdentifier
    session.execute(delete(IdentityProviderIdentifier).where(IdentityProviderIdentifier.user_id.in_(user_ids)))

    # Clear provider_details_history
    stmt = (
        update(ProviderDetailsHistory)
        .where(ProviderDetailsHistory.created_by_id.in_(user_ids))
        .values(created_by_id=None)
    )
    session.execute(stmt)

    # Clear provider_details
    stmt = update(ProviderDetails).where(ProviderDetails.created_by_id.in_(user_ids)).values(created_by_id=None)
    session.execute(stmt)

    # Clear permissions
    session.execute(delete(Permission).where(Permission.user_id.in_(user_ids)))

    # Clear user_to_organisation
    session.execute(delete(user_to_organisation).where(user_to_organisation.c.user_id.in_(user_ids)))

    # Clear user_to_service
    session.execute(delete(ServiceUser).where(ServiceUser.user_id.in_(user_ids)))

    # Clear services created by this user
    stmt = select(Service).where(Service.created_by_id.in_(user_ids))
    service_ids = [s.id for s in session.scalars(stmt).all()]
    if service_ids:
        service_cleanup(service_ids, session, False)

    # Delete the user
    session.execute(delete(User).where(User.id.in_(user_ids)))

    if commit:
        session.commit()


@pytest.fixture
def sample_service_callback(notify_db_session, sample_service):
    service_callback_ids = []

    def _sample_service_callback(
        service: Service,
        url: str = '',
        bearer_token: str = '',
        updated_by_id: UUID = None,
        callback_type: str = '',
        callback_channel: str = WEBHOOK_CHANNEL_TYPE,
        notification_statuses: list = None,
        include_provider_payload: bool = False,
    ):
        # notification_statuses or NOTIFICATION_STATUS_TYPES
        service = service or sample_service()
        updated_by_id = updated_by_id or str(service.users[0].id)

        data = {
            'service_id': service.id,
            'url': url or f'https://something{uuid4()}.com',
            'bearer_token': bearer_token or str(uuid4()),
            'updated_by_id': updated_by_id,
            'callback_type': callback_type or DELIVERY_STATUS_CALLBACK_TYPE,
            'callback_channel': callback_channel,
            'include_provider_payload': include_provider_payload,
        }

        # Logic in the model dictates only callback type of DELIVERY_STATUS_CALLBACK_TYPE may have notification_statuses
        if data['callback_type'] == DELIVERY_STATUS_CALLBACK_TYPE:
            data['notification_statuses'] = notification_statuses or NOTIFICATION_STATUS_TYPES

        service_callback = ServiceCallback(**data)
        notify_db_session.session.add(service_callback)
        notify_db_session.session.commit()
        service_callback_ids.append(service_callback.id)

        return service_callback

    yield _sample_service_callback

    # Teardown
    stmt = delete(ServiceCallback).where(ServiceCallback.id.in_(service_callback_ids))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture(scope='function')
def sample_user_service_role(notify_db_session, sample_service):
    service = sample_service()
    user_service_role = UserServiceRoles(
        user_id=service.users[0].id,
        service_id=service.id,
        role='admin',
        created_at=datetime.utcnow(),
    )

    yield user_service_role


@pytest.fixture(scope='function')
def sample_service_role_udpated(notify_db_session, sample_service):
    service = sample_service()
    user_service_role = UserServiceRoles(
        user_id=service.users[0].id,
        service_id=sample_service().id,
        role='admin',
        created_at=datetime_in_past(days=3),
        updated_at=datetime.utcnow(),
    )

    yield user_service_role


@pytest.fixture
def sample_domain(notify_db_session):
    domain_domains = []

    def _wrapper(domain: str, organisation_id: UUID):
        domain = Domain(domain=domain, organisation_id=organisation_id)

        notify_db_session.session.add(domain)
        notify_db_session.session.commit()

        domain_domains.append(domain.domain)
        return domain

    yield _wrapper

    # Teardown
    for domain_domain in domain_domains:
        stmt = delete(Domain).where(Domain.domain == domain_domain)
        notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


def create_code(notify_db_session, code_type, usr=None, code=None):
    if code is None:
        code = create_secret_code()
    if usr is None:
        usr = create_user()
    return create_user_code(usr, code, code_type), code


def create_user_model(
    mobile_number='+16502532222',
    email='notify@notify.va.gov',
    state='active',
    id_=None,
    name='Test User',
    blocked=False,
):
    data = {
        'id': id_ or uuid4(),
        'name': name,
        'email_address': email,
        'password': 'password',
        'mobile_number': mobile_number,
        'state': state,
        'blocked': blocked,
    }
    user = User(**data)
    return user


def create_service_model(
    user=None,
    service_name='Test service',
    restricted=False,
    count_as_live=True,
    research_mode=False,
    active=True,
    email_from=None,
    prefix_sms=True,
    message_limit=1000,
    organisation_type='other',
    go_live_user=None,
    go_live_at=None,
    crown=True,
    organisation=None,
    smtp_user=None,
) -> Service:
    service = Service(
        name=service_name,
        message_limit=message_limit,
        restricted=restricted,
        email_from=email_from or f'{service_name.lower().replace(" ", ".")}@va.gov',
        created_by=user if user else create_user_model(),
        prefix_sms=prefix_sms,
        organisation_type=organisation_type,
        go_live_user=go_live_user,
        go_live_at=go_live_at,
        crown=crown,
        smtp_user=smtp_user,
        organisation=organisation if organisation else Organisation(id=uuid4(), name='sample organization'),
    )
    service.active = active
    service.research_mode = research_mode
    service.count_as_live = count_as_live

    return service


def create_template_model(
    service,
    template_type=EMAIL_TYPE,
    template_name=None,
    subject='Template subject',
    content='Dear Sir/Madam, Hello. Yours Truly, The Government.',
    reply_to=None,
    hidden=False,
    folder=None,
    process_type='normal',
):
    data = {
        'id': uuid4(),
        'name': template_name or '{} Template Name'.format(template_type),
        'template_type': template_type,
        'content': content,
        'service': service,
        'created_by': service.created_by,
        'reply_to': reply_to,
        'hidden': hidden,
        'folder': folder,
        'process_type': process_type,
    }
    if template_type != SMS_TYPE:
        data['subject'] = subject
    template = Template(**data)

    return template


@pytest.fixture(scope='function')
def sample_notification_model_with_organization(
    service=None,
    template=None,
    job=None,
    job_row_number=None,
    to_field=None,
    status='created',
    reference=None,
    sent_at=None,
    billable_units=1,
    personalisation=None,
    api_key=None,
    key_type=KEY_TYPE_NORMAL,
    sent_by=None,
    client_reference=None,
    rate_multiplier=1.0,
    normalised_to=None,
    postage=None,
    sms_sender_id=None,
) -> Notification:
    created_at = datetime.utcnow()

    if service is None:
        service = create_service_model()

    if template is None:
        template = create_template_model(service=service)

    notification_id = uuid4()

    data = {
        'id': notification_id,
        'to': to_field if to_field else '+16502532222',
        'job_id': job.id if job else None,
        'job': job,
        'service_id': service.id,
        'service': service,
        'template': template,
        'template_id': template.id,
        'template_version': template.version,
        'status': status,
        'reference': reference,
        'created_at': created_at,
        'sent_at': sent_at,
        'billable_units': billable_units,
        'personalisation': personalisation,
        'notification_type': template.template_type,
        'api_key': api_key,
        'api_key_id': api_key and api_key.id,
        'key_type': api_key.key_type if api_key else key_type,
        'sent_by': sent_by,
        'updated_at': None,
        'client_reference': client_reference,
        'rate_multiplier': rate_multiplier,
        'normalised_to': normalised_to,
        'postage': postage,
        'sms_sender_id': sms_sender_id,
    }
    if job_row_number is not None:
        data['job_row_number'] = job_row_number
    notification = Notification(**data)

    return notification


@pytest.fixture
def sample_service(
    notify_db_session,
    sample_user,
    sample_permissions,
    sample_service_permissions,
    sample_sms_sender,
    sample_service_email_reply_to,
):
    created_service_ids = []

    def _sample_service(
        active=True,
        check_if_service_exists=False,
        count_as_live=True,
        crown=True,
        email_address='',
        email_from='',
        go_live_at=None,
        go_live_user=None,
        message_limit=1000,
        organisation=None,
        organisation_type='other',
        prefix_sms=False,
        research_mode=False,
        restricted=False,
        service_id=None,
        service_name=None,
        service_permissions=DEFAULT_SERVICE_NOTIFICATION_PERMISSIONS,
        sms_sender=None,
        smtp_user=None,
        user=None,
    ):
        # Handle where they are checking if it exists by name
        if check_if_service_exists and service_name is not None:
            stmt = select(Service).where(Service.name == service_name)
            service = notify_db_session.session.scalar(stmt)
            return service

        # We do not want create_service to create users because it does not clean them up.
        if user is None:
            user = sample_user(email=f'sample_service_{uuid4()}@va.gov')

        service: Service = sample_service_helper(
            user,
            active=active,
            count_as_live=count_as_live,
            crown=crown,
            email_from=email_from,
            go_live_at=go_live_at,
            go_live_user=go_live_user,
            message_limit=message_limit,
            organisation=organisation,
            organisation_type=organisation_type,
            prefix_sms=prefix_sms,
            research_mode=research_mode,
            restricted=restricted,
            service_id=service_id,
            service_name=service_name,
            smtp_user=smtp_user,
        )
        service.users.append(user)

        sample_service_permissions(service, service_permissions)
        sample_permissions(user, service)
        sample_sms_sender(service.id, sms_sender)
        if email_address is not None:
            sample_service_email_reply_to(service, email_address=email_address)
        # Service should be version 1 in the history after calling this - commits the service
        version_service(service)

        created_service_ids.append(service.id)
        return service

    yield _sample_service

    service_cleanup(created_service_ids, notify_db_session.session)


def sample_service_helper(
    user,
    active=True,
    count_as_live=True,
    crown=True,
    email_from='',
    go_live_at=None,
    go_live_user=None,
    message_limit=1000,
    organisation=None,
    organisation_type='other',
    prefix_sms=False,
    research_mode=False,
    restricted=False,
    service_id=None,
    service_name=None,
    smtp_user=None,
):
    service_name = service_name or f'sample service {uuid4()}'
    kwargs = locals()
    kwargs['created_by'] = kwargs.pop('user')
    kwargs['email_from'] = email_from or f'{service_name.lower().replace(" ", ".")}@va.gov'
    kwargs['id'] = kwargs.pop('service_id') or str(uuid4())
    kwargs['name'] = kwargs.pop('service_name')

    return Service(**kwargs)


def service_cleanup(  # noqa: C901
    service_ids: list,
    session: scoped_session,
    commit: bool = True,
) -> None:
    """
    Cleans up a list of services by deleting all dependencies then clearing the services. Services are used for almost
    everything we do, so the list below is extensive. Without all these here we will need specific ordering on the
    fixtures so one fixture cleans up before it makes it to the sample_service teardown.
    Moved this out of the sample_service fixture for clarity.
    """

    # Clean up service services_history
    # We do not have a all history models. This allows us to have a table for deletions
    # Can't be declared until the app context is declared
    ServicesHistory = Table('services_history', Service.get_history_model().metadata, autoload_with=db.engine)
    ServiceCallbackHistory = Table(
        'service_callback_history', ServiceCallback.get_history_model().metadata, autoload_with=db.engine
    )

    # This is an unfortunate reality of the deep dependency web of our database
    for service_id in service_ids:
        # Clear complaints
        session.execute(delete(Complaint).where(Complaint.service_id == service_id))

        # Clear service_data_retention
        session.execute(delete(ServiceDataRetention).where(ServiceDataRetention.service_id == service_id))

        # Clear service_whitelist
        session.execute(delete(ServiceWhitelist).where(ServiceWhitelist.service_id == service_id))

        # Clear annual_billing
        session.execute(delete(AnnualBilling).where(AnnualBilling.service_id == service_id))

        # Clear ft_billing
        session.execute(delete(FactBilling).where(FactBilling.service_id == service_id))

        # Clear providers from service
        stmt = update(Service).where(Service.id == service_id).values(email_provider_id=None, sms_provider_id=None)
        session.execute(stmt)

        # Clear service_letter_contacts
        session.execute(delete(ServiceLetterContact).where(ServiceLetterContact.service_id == service_id))

        # Clear template_folder
        session.execute(delete(TemplateFolder).where(TemplateFolder.service_id == service_id))

        # Clear user_to_service
        session.execute(delete(user_folder_permissions).where(user_folder_permissions.c.service_id == service_id))

        # Clear all notifications (necessary for key deletion)
        session.execute(delete(Notification).where(Notification.service_id == service_id))
        session.execute(delete(NotificationHistory).where(NotificationHistory.service_id == service_id))

        # Clear all keys
        session.execute(delete(ApiKey).where(ApiKey.service_id == service_id))
        ApiKeyHistory = ApiKey.get_history_model()
        session.execute(delete(ApiKeyHistory).where(ApiKeyHistory.service_id == service_id))

        # Clear all permissions
        session.execute(delete(ServicePermission).where(ServicePermission.service_id == service_id))
        session.execute(delete(Permission).where(Permission.service_id == service_id))

        # Clear all service_sms_senders
        session.execute(delete(ServiceSmsSender).where(ServiceSmsSender.service_id == service_id))

        session.execute(delete(ServicesHistory).where(ServicesHistory.c.id == service_id))
        session.execute(delete(ServiceCallbackHistory).where(ServiceCallbackHistory.c.service_id == service_id))

        session.execute(delete(ServiceCallback).where(ServiceCallback.service_id == service_id))

        # Clear user_to_service
        session.execute(delete(ServiceUser).where(ServiceUser.service_id == service_id))

        # Clear inbound_numbers
        session.execute(delete(InboundNumber).where(InboundNumber.service_id == service_id))

        # Clear inbound_numbers
        session.execute(delete(InboundSms).where(InboundSms.service_id == service_id))

        # Clear service_email_reply_to
        session.execute(delete(ServiceEmailReplyTo).where(ServiceEmailReplyTo.service_id == service_id))

        session.execute(delete(Service).where(Service.id == service_id))
    if commit:
        session.commit()


@pytest.fixture
def sample_service_permissions(notify_db_session):
    service_permissions = []

    def _wrapper(service: Service, permissions: list = DEFAULT_SERVICE_NOTIFICATION_PERMISSIONS):
        for perm in permissions:
            service_permission = ServicePermission(service_id=service.id, permission=perm)
            notify_db_session.session.add(service_permission)
            service.permissions.append(service_permission)
            service_permissions.append((service.id, perm))

        if len(permissions) > 0:
            notify_db_session.session.add(service)
            notify_db_session.session.commit()
        return service.permissions

    yield _wrapper

    # Teardown
    for service_id, perm in service_permissions:
        stmt = delete(ServicePermission).where(
            ServicePermission.service_id == service_id,
            ServicePermission.permission == perm,
        )
        notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def sample_permissions(notify_db_session):
    perm_ids = []

    def _wrapper(user, service, permissions=DEFAULT_SERVICE_MANAGEMENT_PERMISSIONS):
        for name in permissions:
            permission = Permission(permission=name, user=user, service=service)
            notify_db_session.session.add(permission)
            notify_db_session.session.commit()
            perm_ids.append(permission.id)

    yield _wrapper

    # Teardown
    stmt = delete(Permission).where(Permission.id.in_(perm_ids))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


def sample_template_helper(
    name,
    template_type,
    service,
    user,
    content=None,
    archived=False,
    folder=None,
    hidden=False,
    postage=None,
    subject_line=None,
    reply_to=None,
    reply_to_email=None,
    process_type=TEMPLATE_PROCESS_NORMAL,
    version=0,
    id=None,
    communication_item_id=None,
) -> dict:
    """
    Return a dictionary of data for creating a Template or TemplateHistory instance.
    """

    data = {
        'name': name,
        'template_type': template_type,
        'content': content or 'This is a template.',
        'service': service,
        'created_by': user,
        'archived': archived,
        'folder': folder,
        'hidden': hidden,
        'postage': postage,
        'reply_to': reply_to,
        'reply_to_email': reply_to_email,
        'process_type': process_type,
        'version': version,
        'id': id,
        'communication_item_id': communication_item_id,
    }

    if template_type == EMAIL_TYPE:
        data['subject'] = subject_line or 'Subject'

    return data


@pytest.fixture
def sample_template(
    notify_db_session,
    sample_communication_item,
    sample_service,
    sample_user,
):
    template_ids = []

    def _sample_template(
        archived=False,
        communication_item_id=None,
        content=None,
        name=None,
        folder=None,
        hidden=False,
        id=None,
        postage=None,
        process_type=TEMPLATE_PROCESS_NORMAL,
        reply_to=None,
        reply_to_email=None,
        service=None,
        subject=None,
        template_type=SMS_TYPE,
        user=None,
        version=0,
    ):
        # Mandatory arguments - ignore args
        if name is None:
            name = f'function template {uuid4()}'

        # Using fixtures as defaults creates those objects! Do not make a fixture the default param
        if user is None:
            user = sample_user()

        if service is None:
            service = sample_service()

        if communication_item_id is None:
            communication_item_id = sample_communication_item().id

        template_data = sample_template_helper(
            name,
            template_type,
            service,
            user,
            archived=archived,
            content=content,
            folder=folder,
            hidden=hidden,
            postage=postage,
            subject_line=subject,
            reply_to=reply_to,
            reply_to_email=reply_to_email,
            process_type=process_type,
            version=version,
            id=id,
            communication_item_id=communication_item_id,
        )

        if template_type == LETTER_TYPE:
            template_data['postage'] = postage or 'second'

        # Create template object and put it in the DB
        template_dao = Template(**template_data)
        dao_create_template(template_dao)

        # DAO methods use a different session. Using notify_db_session for consistency
        template = notify_db_session.session.get(Template, template_dao.id)
        template_ids.append(template.id)

        return template

    yield _sample_template

    # Teardown
    template_cleanup(notify_db_session.session, template_ids)


def template_cleanup(
    session: scoped_session,
    template_ids: Union[UUID, List[UUID]],
    commit: bool = True,
):
    """
    Cleans the database of templates
    """
    if not isinstance(template_ids, list):
        template_ids = [template_ids]

    # Remove from ft_billing
    stmt = delete(FactBilling).where(FactBilling.template_id.in_(template_ids))
    session.execute(stmt)

    # Remove job for this template
    stmt = delete(Job).where(Job.template_id.in_(template_ids))
    session.execute(stmt)

    # Remove notifications for this template
    stmt = delete(Notification).where(Notification.template_id.in_(template_ids))
    session.execute(stmt)

    # Remove notifications for this template
    stmt = delete(NotificationHistory).where(NotificationHistory.template_id.in_(template_ids))
    session.execute(stmt)

    # Remove history
    stmt = delete(TemplateHistory).where(TemplateHistory.id.in_(template_ids))
    session.execute(stmt)

    # Remove Redacted
    stmt = delete(TemplateRedacted).where(TemplateRedacted.template_id.in_(template_ids))
    session.execute(stmt)

    # Remove template
    stmt = delete(Template).where(Template.id.in_(template_ids))
    session.execute(stmt)

    if commit:
        session.commit()


@pytest.fixture
def sample_template_folder(notify_db_session, sample_service):
    template_folder_ids = []

    def _wrapper(service: Service = None, name='', parent=None):
        service = service or sample_service()
        name = name or str(uuid4())
        template_folder = TemplateFolder(
            service_id=service.id,
            name=name,
            parent=parent,
        )

        notify_db_session.session.add(template_folder)
        notify_db_session.session.commit()
        template_folder_ids.append(template_folder.id)

        return template_folder

    yield _wrapper

    # Teardown
    template_folder_cleanup(template_folder_ids, notify_db_session.session)


def template_folder_cleanup(
    template_folder_ids: List[str],
    session: scoped_session,
    commit: bool = True,
) -> None:
    """
    Helper method to clean template_folders
    """

    # Teardown (order matters)
    # Delete user_folder_permissions records
    stmt = delete(user_folder_permissions).where(user_folder_permissions.c.template_folder_id.in_(template_folder_ids))
    session.execute(stmt)

    # Delete template_folder_map records
    stmt = delete(template_folder_map).where(template_folder_map.c.template_folder_id.in_(template_folder_ids))
    session.execute(stmt)

    # Delete any created template folders
    stmt = delete(TemplateFolder).where(TemplateFolder.id.in_(template_folder_ids))
    session.execute(stmt)

    if commit:
        session.commit()


@pytest.fixture
def sample_letter_template(sample_service, sample_template):
    service = sample_service(service_permissions=[LETTER_TYPE])
    return sample_template(service=service, template_type=LETTER_TYPE, postage='second')


@pytest.fixture
def sample_api_key(notify_db_session, sample_service):
    created_key_ids = []

    def _sample_api_key(service=None, key_type=KEY_TYPE_NORMAL, key_name=None, expired=False):
        if service is None:
            service = sample_service()

        # commits the created key
        api_key = create_api_key(service, key_type, key_name, expired)
        version_api_key(api_key)
        created_key_ids.append(api_key.id)
        return api_key

    yield _sample_api_key

    # Teardown
    # No model for api_keys_history
    ApiKeyHistory = Table('api_keys_history', ApiKey.get_history_model().metadata, autoload_with=db.engine)
    stmt = delete(ApiKeyHistory).where(ApiKeyHistory.c.id.in_(created_key_ids))
    notify_db_session.session.execute(stmt)

    stmt = delete(ApiKey).where(ApiKey.id.in_(created_key_ids))
    notify_db_session.session.execute(stmt)

    # Clear notifications
    stmt = delete(Notification).where(Notification.api_key_id.in_(created_key_ids))
    notify_db_session.session.execute(stmt)

    stmt = delete(NotificationHistory).where(NotificationHistory.api_key_id.in_(created_key_ids))
    notify_db_session.session.execute(stmt)

    notify_db_session.session.commit()


@pytest.fixture
def sample_user_service_api_key(notify_db_session, sample_api_key, sample_user, sample_service):
    """
    Return a related user, service, and API key.  The user and API key are associated with the service.
    The user is not admin, and the API key is "normal" type.
    """
    user = sample_user()
    service = sample_service(user=user)
    assert service.created_by == user
    api_key = sample_api_key(service)
    assert api_key in service.api_keys
    return user, service, api_key


@pytest.fixture
def sample_test_api_key(sample_api_key):
    return sample_api_key(key_type=KEY_TYPE_TEST)


@pytest.fixture
def sample_team_api_key(sample_api_key):
    return sample_api_key(key_type=KEY_TYPE_TEAM)


@pytest.fixture
def sample_job(notify_db_session):
    created_job_ids = []

    def _sample_job(template, **kwargs):
        # commits the job
        job = create_job(template, **kwargs)

        created_job_ids.append(job.id)

        return job

    yield _sample_job

    # Teardown
    stmt = delete(Notification).where(Notification.job_id.in_(created_job_ids))
    notify_db_session.session.execute(stmt)

    stmt = delete(NotificationHistory).where(NotificationHistory.job_id.in_(created_job_ids))
    notify_db_session.session.execute(stmt)

    stmt = delete(Job).where(Job.id.in_(created_job_ids))
    notify_db_session.session.execute(stmt)

    notify_db_session.session.commit()


@pytest.fixture
def sample_scheduled_job(sample_job, sample_template):
    return sample_job(
        sample_template(content='Hello (( Name))\nYour thing is due soon'),
        job_status=JOB_STATUS_SCHEDULED,
        scheduled_for=(datetime.utcnow() + timedelta(minutes=60)).isoformat(),
    )


@pytest.fixture
def sample_annual_billing(
    notify_db_session,
):
    billing_ids = []

    def _sample_annual_billing(
        service_id,
        free_sms_fragment_limit,
        financial_year_start,
    ):
        annual_billing = AnnualBilling(
            service_id=service_id,
            free_sms_fragment_limit=free_sms_fragment_limit,
            financial_year_start=financial_year_start,
        )
        notify_db_session.session.add(annual_billing)
        notify_db_session.session.commit()

        billing_ids.append(annual_billing.id)

        return annual_billing

    yield _sample_annual_billing

    # Teardown
    stmt = delete(AnnualBilling).where(AnnualBilling.id.in_(billing_ids))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def sample_ft_billing(
    notify_db_session,
    sample_service,
    sample_template,
):
    ft_billing_bsts = []

    def _sample_ft_billing(
        utc_date,
        notification_type,
        template=None,
        service=None,
        provider='test',
        rate_multiplier=1,
        international=False,
        rate=0,
        billable_unit=1,
        notifications_sent=1,
        postage='none',
    ):
        if not service:
            service = sample_service()
        if not template:
            template = sample_template(service=service, template_type=notification_type)

        data = FactBilling(
            bst_date=utc_date,
            service_id=service.id,
            template_id=template.id,
            notification_type=notification_type,
            provider=provider,
            rate_multiplier=rate_multiplier,
            international=international,
            rate=rate,
            billable_units=billable_unit,
            notifications_sent=notifications_sent,
            postage=postage,
        )

        save_data = (
            utc_date,
            service.id,
            template.id,
            notification_type,
            provider,
            rate_multiplier,
            international,
            rate,
            postage,
        )

        notify_db_session.session.add(data)
        notify_db_session.session.commit()

        ft_billing_bsts.append(save_data)

        return data

    yield _sample_ft_billing

    # Teardown
    # FactBilling has a compound key comprised of NINE fields
    for (
        bst_date,
        service_id,
        template_id,
        notification_type,
        provider,
        rate_multiplier,
        international,
        rate,
        postage,
    ) in ft_billing_bsts:
        stmt = delete(FactBilling).where(
            FactBilling.bst_date == bst_date,
            FactBilling.service_id == service_id,
            FactBilling.template_id == template_id,
            FactBilling.notification_type == notification_type,
            FactBilling.provider == provider,
            FactBilling.rate_multiplier == rate_multiplier,
            FactBilling.international == international,
            FactBilling.rate == rate,
            FactBilling.postage == postage,
        )
        notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def sample_ft_notification_status(notify_db_session, sample_template, sample_job):
    created_ft_notification_statuses: list[dict] = []

    def _sample_ft_notification_status(
        utc_date,
        job=None,
        key_type='normal',
        notification_status='delivered',
        status_reason='',
        count=1,
    ):
        if job is None:
            job = sample_job(sample_template())

        template = job.template

        pk_data = {
            'bst_date': utc_date,
            'template_id': template.id,
            'service_id': template.service.id,
            'job_id': job.id,
            'notification_type': template.template_type,
            'key_type': key_type,
            'notification_status': notification_status,
        }

        ft_notification_status = FactNotificationStatus(
            **pk_data,
            status_reason=status_reason,
            notification_count=count,
        )
        notify_db_session.session.add(ft_notification_status)
        notify_db_session.session.commit()
        created_ft_notification_statuses.append(pk_data)

        return ft_notification_status

    yield _sample_ft_notification_status

    # Teardown
    for pk_data in created_ft_notification_statuses:
        b, t, s, j, nt, k, ns = pk_data.values()
        # This monstrosity has 9 primary keys
        stmt = delete(FactNotificationStatus).where(
            FactNotificationStatus.bst_date == b,
            FactNotificationStatus.template_id == t,
            FactNotificationStatus.service_id == s,
            FactNotificationStatus.job_id == j,
            FactNotificationStatus.notification_type == nt,
            FactNotificationStatus.key_type == k,
            FactNotificationStatus.notification_status == ns,
        )
        notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def set_up_usage_data(
    sample_annual_billing,
    sample_ft_billing,
    sample_organisation,
    sample_service,
    sample_template,
):
    def _set_up_usage_data(start_date):
        """
        Organizations and Services have sortable names to faciliate testing.
        """

        year = int(start_date.strftime('%Y'))
        one_week_earlier = start_date - timedelta(days=7)
        two_days_later = start_date + timedelta(days=2)
        one_week_later = start_date + timedelta(days=7)
        one_month_later = start_date + timedelta(days=31)

        service = sample_service(service_name=f'a service {uuid4()}')  # with sms and letter
        letter_template = sample_template(service=service, template_type=LETTER_TYPE)
        sms_template_1 = sample_template(service=service, template_type=SMS_TYPE)
        sample_annual_billing(service_id=service.id, free_sms_fragment_limit=10, financial_year_start=year)
        org = sample_organisation(name=f'a Org for {service.name}')
        dao_add_service_to_organisation(service=service, organisation_id=org.id)

        service_3 = sample_service(service_name=f'b service {uuid4()}')  # letters only
        template_3 = sample_template(service=service_3)
        org_3 = sample_organisation(name=f'b Org for {service_3.name}')
        dao_add_service_to_organisation(service=service_3, organisation_id=org_3.id)

        service_4 = sample_service(service_name=f'c service {uuid4()}')  # service without org
        template_4 = sample_template(service=service_4, template_type=LETTER_TYPE)

        service_sms_only = sample_service(service_name=f'd service {uuid4()}')  # chargeable sms
        sms_template = sample_template(service=service_sms_only, template_type=SMS_TYPE)
        sample_annual_billing(service_id=service_sms_only.id, free_sms_fragment_limit=10, financial_year_start=year)

        sample_ft_billing(
            utc_date=one_week_earlier,
            service=service,
            notification_type=SMS_TYPE,
            template=sms_template_1,
            billable_unit=2,
            rate=0.11,
        )
        sample_ft_billing(
            utc_date=start_date,
            service=service,
            notification_type=SMS_TYPE,
            template=sms_template_1,
            billable_unit=2,
            rate=0.11,
        )
        sample_ft_billing(
            utc_date=two_days_later,
            service=service,
            notification_type=SMS_TYPE,
            template=sms_template_1,
            billable_unit=1,
            rate=0.11,
        )
        sample_ft_billing(
            utc_date=one_week_later,
            service=service,
            notification_type=LETTER_TYPE,
            template=letter_template,
            notifications_sent=2,
            billable_unit=1,
            rate=0.35,
            postage='first',
        )
        sample_ft_billing(
            utc_date=one_month_later,
            service=service,
            notification_type=LETTER_TYPE,
            template=letter_template,
            notifications_sent=4,
            billable_unit=2,
            rate=0.45,
            postage='second',
        )
        sample_ft_billing(
            utc_date=one_week_later,
            service=service,
            notification_type=LETTER_TYPE,
            template=letter_template,
            notifications_sent=2,
            billable_unit=2,
            rate=0.45,
            postage='second',
        )

        sample_ft_billing(
            utc_date=one_week_earlier,
            service=service_sms_only,
            notification_type=SMS_TYPE,
            template=sms_template,
            rate=0.11,
            billable_unit=12,
        )
        sample_ft_billing(
            utc_date=two_days_later,
            service=service_sms_only,
            notification_type=SMS_TYPE,
            template=sms_template,
            rate=0.11,
        )
        sample_ft_billing(
            utc_date=one_week_later,
            service=service_sms_only,
            notification_type=SMS_TYPE,
            template=sms_template,
            billable_unit=2,
            rate=0.11,
        )

        sample_ft_billing(
            utc_date=start_date,
            service=service_3,
            notification_type=LETTER_TYPE,
            template=template_3,
            notifications_sent=2,
            billable_unit=3,
            rate=0.50,
            postage='first',
        )
        sample_ft_billing(
            utc_date=one_week_later,
            service=service_3,
            notification_type=LETTER_TYPE,
            template=template_3,
            notifications_sent=8,
            billable_unit=5,
            rate=0.65,
            postage='second',
        )
        sample_ft_billing(
            utc_date=one_month_later,
            service=service_3,
            notification_type=LETTER_TYPE,
            template=template_3,
            notifications_sent=12,
            billable_unit=5,
            rate=0.65,
            postage='second',
        )

        sample_ft_billing(
            utc_date=two_days_later,
            service=service_4,
            notification_type=LETTER_TYPE,
            template=template_4,
            notifications_sent=15,
            billable_unit=4,
            rate=0.55,
            postage='second',
        )

        return org, org_3, service, service_3, service_4, service_sms_only

    yield _set_up_usage_data

    # Teardown should be handled by the constituent fixtures.


@pytest.fixture
def sample_notification_with_job(
    notify_db_session,
    sample_service,
    sample_template,
    sample_job,
    sample_sms_sender,
    service=None,
    template=None,
    job=None,
    job_row_number=None,
    to_field=None,
    status='created',
    reference=None,
    created_at=None,
    sent_at=None,
    billable_units=1,
    personalisation=None,
    api_key=None,
    key_type=KEY_TYPE_NORMAL,
):
    if service is None:
        service = sample_service(check_if_service_exists=True)
    if template is None:
        template = sample_template(service=service)
        assert template.template_type == SMS_TYPE, 'This is the default template type.'
    if job is None:
        job = sample_job(template)

    yield create_notification(
        template=template,
        job=job,
        job_row_number=job_row_number if job_row_number is not None else None,
        to_field=to_field,
        status=status,
        reference=reference,
        created_at=created_at,
        sent_at=sent_at,
        billable_units=billable_units,
        personalisation=personalisation,
        api_key=api_key,
        key_type=key_type,
        sms_sender_id=sample_sms_sender(service.id).id,
    )

    # Teardown
    notify_db_session.session.execute(delete(Notification).where(Notification.service_id == service.id))


@pytest.fixture
def sample_notification(notify_db_session, sample_api_key, sample_template):  # noqa C901
    created_notification_ids = []

    def _sample_notification(*args, gen_type: str = SMS_TYPE, **kwargs):
        # sample_notification should have been split into API called notifications and non-api notifications
        # Some behavior can be shared
        # Default behavior with no args or a specified generation type
        if len(kwargs) == 0:
            template = sample_template(template_type=gen_type)
            kwargs['api_key'] = sample_api_key(service=template.service)
            kwargs['template'] = template

        if kwargs.get('created_at') is None:
            kwargs['created_at'] = datetime.utcnow()

        if kwargs.get('template') is None:
            template = sample_template()
            kwargs['template'] = template
            assert template.template_type == SMS_TYPE, 'This is the default template type.'

        if kwargs.get('job') is None and kwargs.get('api_key') is None and kwargs.get('one_off') is None:
            stmt = select(ApiKey).where(
                ApiKey.service_id == kwargs['template'].service.id,
                ApiKey.key_type == kwargs.get('key_type', KEY_TYPE_NORMAL),
            )
            api_key = notify_db_session.session.scalar(stmt)

            if not api_key:
                api_key = sample_api_key(kwargs['template'].service, key_type=kwargs.get('key_type', KEY_TYPE_NORMAL))
            kwargs['api_key'] = api_key

        # This intentionally excludes the case where created_by_id=None.
        if 'created_by_id' not in kwargs:
            kwargs['created_by_id'] = kwargs['template'].created_by_id

        # xdist has issues with parameterize and allowing the DB to set the notification id
        kwargs['reference'] = kwargs.get('reference', str(uuid4()))

        # commits the notification
        notification = create_notification(*args, **kwargs)
        created_notification_ids.append(notification.id)

        return notification

    yield _sample_notification

    # Teardown
    stmt = delete(RecipientIdentifier).where(RecipientIdentifier.notification_id.in_(created_notification_ids))
    notify_db_session.session.execute(stmt)

    stmt = delete(ScheduledNotification).where(ScheduledNotification.notification_id.in_(created_notification_ids))
    notify_db_session.session.execute(stmt)

    stmt = delete(Notification).where(Notification.id.in_(created_notification_ids))
    notify_db_session.session.execute(stmt)

    stmt = delete(NotificationHistory).where(NotificationHistory.id.in_(created_notification_ids))
    notify_db_session.session.execute(stmt)

    notify_db_session.session.commit()


@pytest.fixture
def sample_notification_history(
    notify_db_session,
    sample_template,
    sample_api_key,
):
    created_notification_histories = []

    def _sample_notification_history(
        status='created',
        template=None,
        created_at=None,
        key_type=KEY_TYPE_NORMAL,
        sent_at=None,
        reference=None,
        api_key=None,
        sms_sender_id=None,
    ):
        if template is None:
            template = sample_template()
            assert template.template_type == SMS_TYPE, 'This is the default.'

        if created_at is None:
            created_at = datetime.utcnow()

        if sent_at is None:
            sent_at = datetime.utcnow()

        if api_key is None:
            api_key = sample_api_key(template.service, key_type=key_type)

        notification_history = NotificationHistory(
            id=uuid4(),
            service=template.service,
            template_id=template.id,
            template_version=template.version,
            status=status,
            created_at=created_at,
            notification_type=template.template_type,
            key_type=key_type,
            api_key=api_key,
            api_key_id=api_key.id,
            reference=reference,
            sent_at=sent_at,
            sms_sender_id=sms_sender_id,
        )
        notify_db_session.session.add(notification_history)
        notify_db_session.session.commit()
        created_notification_histories.append(notification_history.id)

        return notification_history

    yield _sample_notification_history

    # Teardown
    stmt = delete(NotificationHistory).where(NotificationHistory.id.in_(created_notification_histories))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def sample_invited_user(notify_db_session, sample_service):
    created_invited_user_ids = []

    def _sample_invited_user(service: Service = None, to_email_address: str = None, created_at: datetime = None):
        if service is None:
            service = sample_service(check_if_service_exists=True)

        if to_email_address is None:
            to_email_address = f'{uuid4()}@digital.gov.uk'

        from_user = service.users[0]

        data = {
            'service': service,
            'email_address': to_email_address,
            'from_user': from_user,
            'permissions': 'send_messages,manage_service,manage_api_keys',
            'folder_permissions': ['folder_1_id', 'folder_2_id'],
        }

        if created_at is not None:
            data['created_at'] = created_at

        invited_user = InvitedUser(**data)
        # commits the invited user
        save_invited_user(invited_user)
        created_invited_user_ids.append(invited_user.id)

        return invited_user

    yield _sample_invited_user

    # Teardown
    stmt = delete(InvitedUser).where(InvitedUser.id.in_(created_invited_user_ids))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def sample_invited_org_user(notify_db_session, sample_organisation, sample_user):
    created_invited_organisation_users = []

    def _sample_invited_org_user(organisation=None, invited_by=None, email_address=f'{uuid4()}@example.com'):
        if organisation is None:
            organisation = sample_organisation()

        if invited_by is None:
            invited_by = sample_user()

        invited_org_user = InvitedOrganisationUser(
            email_address=email_address,
            invited_by=invited_by,
            organisation=organisation,
        )
        notify_db_session.session.add(invited_org_user)
        notify_db_session.session.commit()
        created_invited_organisation_users.append(invited_org_user)

        return invited_org_user

    yield _sample_invited_org_user

    # Teardown
    for invited_org_user in created_invited_organisation_users:
        notify_db_session.session.delete(invited_org_user)
    notify_db_session.session.commit()


@pytest.fixture(scope='function')
def fake_uuid():
    return '6ce466d0-fd6a-11e5-82f5-e0accb9d11a6'


@pytest.fixture
def fake_uuid_v2():
    """
    Generates a unique uuid per function
    """
    return uuid4()


@pytest.fixture
def sample_provider(notify_db_session, worker_id):
    created_provider_ids = {worker_id: []}

    def _sample_provider(
        identifier: str = PINPOINT_PROVIDER,
        get: bool = False,
        display_name: str = '',
        priority: int = 10,
        notification_type: Union[EMAIL_TYPE, SMS_TYPE] = SMS_TYPE,
        active: bool = True,
        supports_international: bool = False,
        created_by: User = None,
        created_by_id: UUID = None,
        load_balancing_weight: int = None,
    ):
        """
        Return a ProviderDetails instance.  If the paramter "get" is True, this function will attempt
        to return an existing Provider with the given identifier.  If that fails, the function
        creates a new Provider (same as get=False).
        """

        if get:
            stmt = select(ProviderDetails).where(ProviderDetails.identifier == identifier)
            provider = notify_db_session.session.scalar(stmt)

            if provider is not None:
                return provider

        data = {
            'display_name': display_name or f'provider_{uuid4()}',
            'identifier': identifier,
            'priority': priority,
            'notification_type': notification_type,
            'active': active,
            'supports_international': supports_international,
            'created_by': created_by,
            'created_by_id': created_by_id,
            'load_balancing_weight': load_balancing_weight,
        }

        # Set created_by or created_by_id if the other exists
        if created_by and not created_by_id:
            data['created_by_id'] = str(created_by.id)
        if created_by_id and not created_by:
            data['created_by'] = notify_db_session.session.get(User, created_by_id)

        # Add provider_details
        provider = ProviderDetails(**data)
        notify_db_session.session.add(provider)
        notify_db_session.session.commit()
        created_provider_ids[worker_id].append(provider.id)

        # Add provider_details_history - Has to happen after the provider_details are commit
        history = ProviderDetailsHistory.from_original(provider)
        notify_db_session.session.add(history)
        notify_db_session.session.commit()

        return provider

    yield _sample_provider

    # Teardown
    stmt = delete(ProviderDetailsHistory).where(ProviderDetailsHistory.id.in_(created_provider_ids[worker_id]))
    notify_db_session.session.execute(stmt)

    stmt = delete(ProviderDetails).where(ProviderDetails.id.in_(created_provider_ids[worker_id]))
    notify_db_session.session.execute(stmt)

    notify_db_session.session.commit()


@pytest.fixture(scope='function')
def mock_firetext_client(mocker, statsd_client=None):
    client = FiretextClient()
    statsd_client = statsd_client or mocker.Mock()
    current_app = mocker.Mock(
        config={'FIRETEXT_URL': 'https://example.com/firetext', 'FIRETEXT_API_KEY': 'foo', 'FROM_NUMBER': 'bar'}
    )
    client.init_app(current_app, statsd_client)
    return client


@pytest.fixture
def sample_smtp_template(sample_service, sample_template):
    def _wrapper():
        service = sample_service(smtp_user=f'{uuid4()}@smtp_user')

        return sample_template(
            service=service,
            user=service.created_by,
            name='SMTP_TEMPLATE_ID',
            content=('((message))'),
            subject='((subject))',
            template_type=EMAIL_TYPE,
        )

    yield _wrapper


@pytest.fixture(scope='function')
def sample_service_whitelist(notify_db_session, sample_service):
    whitelist_user_ids = []

    def _wrapper(service: Service = None, email_address: str = '', phone_number: str = '', mobile_number: str = ''):
        service = service or sample_service(check_if_service_exists=True)

        if email_address:
            whitelisted_user = ServiceWhitelist.from_string(service.id, EMAIL_TYPE, email_address)
        elif phone_number or mobile_number:
            whitelisted_user = ServiceWhitelist.from_string(service.id, MOBILE_TYPE, phone_number or mobile_number)
        else:
            whitelisted_user = ServiceWhitelist.from_string(service.id, EMAIL_TYPE, 'whitelisted_user@va.gov')

        notify_db_session.session.add(whitelisted_user)
        notify_db_session.session.commit()
        whitelist_user_ids.append(whitelisted_user.id)

        return whitelisted_user

    yield _wrapper

    # Teardown
    for wu_id in whitelist_user_ids:
        stmt = delete(ServiceWhitelist).where(ServiceWhitelist.service_id == wu_id)
        notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def sample_inbound_sms(notify_db_session, sample_service, sample_inbound_number):
    created_inbound_sms_ids = []

    def _sample_inbound_sms(
        service=None,
        notify_number=None,
        user_number='+16502532222',
        provider_date=None,
        provider_reference='foo',
        content='Hello',
        provider=MMG_PROVIDER,
        created_at=None,
    ):
        # Set values if they came in None
        service = service or sample_service()
        provider_date = provider_date or datetime.utcnow()
        created_at = created_at or datetime.utcnow()
        # if notify_number comes in None it is handled by creating an inbound number for the service

        if not service.inbound_numbers:
            # Create inbound_number attached to the service
            sample_inbound_number(number=notify_number, provider=provider, service_id=service.id)

        inbound_sms = InboundSms(
            service=service,
            created_at=created_at,
            notify_number=notify_number or service.inbound_numbers[0].number,
            user_number=user_number,
            provider_date=provider_date,
            provider_reference=provider_reference,
            content=content,
            provider=provider,
        )

        notify_db_session.session.add(inbound_sms)
        notify_db_session.session.commit()
        created_inbound_sms_ids.append(inbound_sms.id)

        return inbound_sms

    yield _sample_inbound_sms

    # Teardown
    stmt = delete(InboundSms).where(InboundSms.id.in_(created_inbound_sms_ids))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def sample_inbound_number(notify_db_session):
    inbound_number_ids = []
    service_ids = []

    def _sample_inbound_number(
        number=None,
        provider='sample',
        active=True,
        service_id=None,
        url_endpoint=None,
        self_managed=False,
    ):
        # Default to the correct amount of characters
        number = number or f'1{randint(100000000, 999999999)}'

        inbound_number = InboundNumber(
            id=uuid4(),
            number=number,
            provider=provider,
            active=active,
            service_id=service_id,
            url_endpoint=url_endpoint,
            self_managed=self_managed,
        )

        notify_db_session.session.add(inbound_number)
        notify_db_session.session.commit()
        inbound_number_ids.append(inbound_number.id)
        service_ids.append(service_id)

        return inbound_number

    yield _sample_inbound_number

    # Teardown
    stmt = update(Notification).where(Notification.service_id.in_(service_ids)).values(sms_sender_id=None)
    notify_db_session.session.execute(stmt)
    stmt = delete(ServiceSmsSender).where(ServiceSmsSender.inbound_number_id.in_(inbound_number_ids))
    notify_db_session.session.execute(stmt)
    stmt = delete(InboundNumber).where(InboundNumber.id.in_(inbound_number_ids))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def sample_inbound_numbers(sample_service, sample_inbound_number):
    service = sample_service(service_name=str(uuid4()), check_if_service_exists=False)
    inbound_numbers = [
        sample_inbound_number(provider=MMG_PROVIDER),
        sample_inbound_number(provider=MMG_PROVIDER, active=False, service_id=service.id),
        sample_inbound_number(provider='firetext', service_id=service.id),
    ]
    return inbound_numbers


@pytest.fixture
def sample_organisation(
    notify_db_session,
    sample_domain,
):
    org_ids = []

    def _sample_organisation(name: str = None, domains: Union[list, None] = None, active: bool = True):
        org = Organisation(name=name or f'sample organisation {uuid4()}', active=active)
        # commits the org
        dao_create_organisation(org)

        org_ids.append(org.id)

        for domain in domains or []:
            sample_domain(domain, org.id)

        return org

    yield _sample_organisation

    # Teardown
    # Update org id in services
    stmt = update(Service).where(Service.organisation_id.in_(org_ids)).values(organisation_id=None)
    notify_db_session.session.execute(stmt)

    # Clear user_to_organisation
    stmt = delete(user_to_organisation).where(user_to_organisation.c.organisation_id.in_(org_ids))
    notify_db_session.session.execute(stmt)

    # Clear InvitedOrganisationUser
    stmt = delete(InvitedOrganisationUser).where(InvitedOrganisationUser.id.in_(org_ids))
    notify_db_session.session.execute(stmt)

    # Clear domains
    stmt = delete(Domain).where(Domain.organisation_id.in_(org_ids))
    notify_db_session.session.execute(stmt)

    # Clear orgs
    stmt = delete(Organisation).where(Organisation.id.in_(org_ids))
    notify_db_session.session.execute(stmt)

    notify_db_session.session.commit()


@pytest.fixture
def aws_credentials():
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'


@pytest.fixture
def sample_login_event(notify_db_session, sample_user):
    created_login_event_ids = []

    def _sample_login_event(user=None):
        if user is None:
            user = sample_user()

        event = LoginEvent(data={'ip': '8.8.8.8', 'user-agent': 'GoogleBot'}, user_id=user.id)
        # commits the login event
        save_login_event(event)
        created_login_event_ids.append(event.id)

        return event

    yield _sample_login_event

    # Teardown
    stmt = delete(LoginEvent).where(LoginEvent.id.in_(created_login_event_ids))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def sample_rate(notify_db_session):
    created_rate_ids = []

    def _sample_rate(start_date, value, notification_type):
        rate = Rate(id=uuid4(), valid_from=start_date, rate=value, notification_type=notification_type)
        notify_db_session.session.add(rate)
        notify_db_session.session.commit()
        created_rate_ids.append(rate.id)
        return rate

    yield _sample_rate

    # Teardown
    stmt = delete(Rate).where(Rate.id.in_(created_rate_ids))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def restore_provider_details(notify_db_session):
    """
    Must be ran serial

    We view ProviderDetails as a static in notify_db_session, since we don't modify it... except we do, we updated
    priority. This fixture is designed to be used in tests that will knowingly touch provider details, to restore them
    to previous state.

    Note: This doesn't technically require notify_db_session (only notify_db), but kept as a requirement to encourage
    good usage.  If you're modifying ProviderDetails's state then it's good to clear down the rest of the DB too.
    """

    stmt = select(ProviderDetails)
    existing_provider_details = notify_db_session.session.scalars(stmt).all()

    stmt = select(ProviderDetailsHistory)
    existing_provider_details_history = notify_db_session.session.scalars(stmt).all()

    # make_transient removes the objects from the session (because we will delete them later).
    for epd in existing_provider_details:
        make_transient(epd)
    for epdh in existing_provider_details_history:
        make_transient(epdh)

    yield notify_db_session

    # Delete ProviderRates because they depend on ProviderDetails.
    notify_db_session.session.execute(delete(ProviderRates))
    notify_db_session.session.execute(delete(ProviderDetails))
    notify_db_session.session.execute(delete(ProviderDetailsHistory))
    notify_db_session.session.commit()

    notify_db_session.session.add_all(existing_provider_details)
    notify_db_session.session.add_all(existing_provider_details_history)
    notify_db_session.session.commit()


@pytest.fixture
def admin_request(client):
    class AdminRequest:
        app = client.application

        @staticmethod
        def get(endpoint, _expected_status=200, **endpoint_kwargs):
            resp = client.get(
                url_for(endpoint, **(endpoint_kwargs or {})), headers=[create_admin_authorization_header()]
            )

            assert resp.status_code == _expected_status
            return resp.json

        @staticmethod
        def post(endpoint, _data=None, _expected_status=200, **endpoint_kwargs):
            resp = client.post(
                url_for(endpoint, **(endpoint_kwargs or {})),
                data=json.dumps(_data),
                headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
            )

            assert resp.status_code == _expected_status
            return resp.json if resp.get_data() else None

        @staticmethod
        def patch(endpoint, _data=None, _expected_status=200, **endpoint_kwargs):
            resp = client.patch(
                url_for(endpoint, **(endpoint_kwargs or {})),
                data=json.dumps(_data),
                headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
            )

            assert resp.status_code == _expected_status
            return resp.json if resp.get_data() else None

        @staticmethod
        def delete(endpoint, _expected_status=204, **endpoint_kwargs):
            resp = client.delete(
                url_for(endpoint, **(endpoint_kwargs or {})), headers=[create_admin_authorization_header()]
            )

            assert resp.status_code == _expected_status
            return resp.json if resp.get_data() else None

    return AdminRequest


@pytest.fixture(scope='function')
def mock_sms_client(mocker):
    mocked_client = SmsClient()
    mocker.patch.object(mocked_client, 'send_sms', return_value='some-reference')
    mocker.patch.object(mocked_client, 'get_name', return_value='Fake SMS Client')
    mocker.patch('app.delivery.send_to_providers.client_to_use', return_value=mocked_client)
    return mocked_client


@pytest.fixture(scope='function')
def mock_email_client(mocker):
    mocked_client = EmailClient()
    mocker.patch.object(mocked_client, 'send_email', return_value='message id')
    mocker.patch.object(mocked_client, 'get_name', return_value='Fake Email Client')
    mocker.patch('app.delivery.send_to_providers.client_to_use', return_value=mocked_client)
    return mocked_client


@pytest.fixture(scope='function')
def mocked_provider_stats(sample_user, mocker):
    return [
        mocker.Mock(
            **{
                'id': uuid4(),
                'display_name': 'foo',
                'identifier': 'foo',
                'priority': 10,
                'notification_type': 'sms',
                'active': True,
                'updated_at': datetime.utcnow(),
                'supports_international': False,
                'created_by_name': sample_user().name,
                'load_balancing_weight': 25,
                'current_month_billable_sms': randrange(100),  # nosec
            }
        ),
        mocker.Mock(
            **{
                'id': uuid4(),
                'display_name': 'bar',
                'identifier': 'bar',
                'priority': 20,
                'notification_type': 'sms',
                'active': True,
                'updated_at': datetime.utcnow(),
                'supports_international': False,
                'created_by_name': sample_user().name,
                'load_balancing_weight': 75,
                'current_month_billable_sms': randrange(100),  # nosec
            }
        ),
    ]


def datetime_in_past(days=0, seconds=0):
    return datetime.now(tz=pytz.utc) - timedelta(days=days, seconds=seconds)


@pytest.fixture
def sample_sms_sender(notify_db_session):
    sms_sender_service_ids = []

    def _wrapper(
        service_id,
        sms_sender=None,
        is_default=True,
        inbound_number_id=None,
        rate_limit=None,
        rate_limit_interval=None,
        sms_sender_specifics=None,
        archived=None,
        provider_id=None,
    ):
        data = {
            'service_id': service_id,
            'provider_id': provider_id,
            'sms_sender': sms_sender or current_app.config['FROM_NUMBER'],
            'is_default': is_default,
            'inbound_number_id': inbound_number_id,
            'rate_limit': rate_limit,
            'rate_limit_interval': rate_limit_interval,
            'sms_sender_specifics': sms_sender_specifics,
            'archived': archived,
        }

        service_sms_sender = ServiceSmsSender(**data)
        notify_db_session.session.add(service_sms_sender)
        notify_db_session.session.commit()
        sms_sender_service_ids.append(service_id)

        return service_sms_sender

    yield _wrapper

    # Teardown
    stmt = update(Notification).where(Notification.service_id.in_(sms_sender_service_ids)).values(sms_sender_id=None)
    notify_db_session.session.execute(stmt)
    stmt = delete(ServiceSmsSender).where(ServiceSmsSender.service_id.in_(sms_sender_service_ids))
    notify_db_session.session.execute(stmt)
    stmt = delete(InboundNumber).where(InboundNumber.service_id.in_(sms_sender_service_ids))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def sample_communication_item(notify_db_session):
    created_communication_item_ids = []
    va_profile_ids = set([])

    def _sample_communication_item(default_send: bool = True):
        va_profile_item_id = randint(111, 10000000)
        # This actually hit a duplicate during testing!
        while va_profile_item_id in va_profile_ids:
            va_profile_item_id = randint(1, 10000000)
        communication_item = CommunicationItem(
            id=uuid4(),
            va_profile_item_id=va_profile_item_id,
            name=uuid4(),
            default_send_indicator=default_send,
        )
        notify_db_session.session.add(communication_item)
        notify_db_session.session.commit()

        created_communication_item_ids.append(communication_item.id)
        va_profile_ids.add(va_profile_item_id)

        return communication_item

    yield _sample_communication_item

    # Teardown
    # Do not clear va_profile_ids
    stmt = delete(CommunicationItem).where(CommunicationItem.id.in_(created_communication_item_ids))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def sample_service_with_inbound_number(
    notify_db_session,
    sample_inbound_number,
    sample_service,
):
    def _wrapper(*args, service: Service = None, inbound_number='', **kwargs):
        inbound_number = inbound_number or randint(10000000, 9999999999)
        service = kwargs.pop('service', None)
        if not service:
            service = sample_service(*args, **kwargs)
        stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
        sms_sender = notify_db_session.session.scalar(stmt)
        ib = sample_inbound_number(number=inbound_number)

        # transactional
        dao_update_service_sms_sender(
            service_id=service.id,
            service_sms_sender_id=sms_sender.id,
            sms_sender=inbound_number,
            inbound_number_id=ib.id,
        )

        return service

    yield _wrapper

    # Teardown - Not required due to other fixtures cleaning up


@pytest.fixture
def sample_service_email_reply_to(notify_db_session):
    service_email_reply_to_ids = []

    def _sample_service_email_reply_to(service: Service, email_address: str = '', **kwargs):
        data = {
            'service': service,
            'service_id': service.id,
            'email_address': email_address or 'vanotify@va.gov',
            'is_default': True,
            'archived': kwargs.get('archived', False),
        }
        service_email_reply_to = ServiceEmailReplyTo(**data)

        notify_db_session.session.add(service_email_reply_to)
        notify_db_session.session.commit()

        if data['is_default']:
            for email in service.reply_to_email_addresses:
                # Set each to False unless it is the new default
                email.is_default = email.id == service_email_reply_to.id
                notify_db_session.session.add(email)
            notify_db_session.session.commit()

        service_email_reply_to_ids.append(service_email_reply_to.id)
        return service_email_reply_to

    yield _sample_service_email_reply_to

    # Teardown
    stmt = delete(ServiceEmailReplyTo).where(ServiceEmailReplyTo.id.in_(service_email_reply_to_ids))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def sample_complaint(notify_db_session, sample_service, sample_template, sample_notification):
    created_complaints = []

    def _sample_complaint(service=None, notification=None, created_at=None):
        if service is None:
            service = sample_service()
        if notification is None:
            template = sample_template(service=service, template_type=EMAIL_TYPE)
            notification = sample_notification(template=template)

        complaint = Complaint(
            notification_id=notification.id,
            service_id=service.id,
            feedback_id=str(uuid4()),
            complaint_type='abuse',
            complaint_date=datetime.utcnow(),
            created_at=created_at if (created_at is not None) else datetime.now(),
        )

        notify_db_session.session.add(complaint)
        notify_db_session.session.commit()
        created_complaints.append(complaint.id)
        return complaint

    yield _sample_complaint

    # Teardown
    stmt = delete(Complaint).where(Complaint.id.in_(created_complaints))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def sample_email_branding(notify_db_session):
    email_branding_ids = []

    def _sample_email_branding(colour='blue', logo='test_x2.png', name='test_org_1', text='DisplayName'):
        data = {
            'colour': colour,
            'logo': logo,
            'name': name,
            'text': text,
        }
        email_branding = EmailBranding(**data)
        notify_db_session.session.add(email_branding)
        notify_db_session.session.commit()
        email_branding_ids.append(email_branding.id)
        return email_branding

    yield _sample_email_branding

    # Teardown
    stmt = delete(EmailBranding).where(EmailBranding.id.in_(email_branding_ids))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def sample_letter_rate(notify_db_session):
    created_letter_rates = []

    def _sample_letter_rate(start_date=None, end_date=None, crown=True, sheet_count=1, rate=0.33, post_class='second'):
        if start_date is None:
            start_date = datetime(2016, 1, 1)
        rate = LetterRate(
            id=uuid4(),
            start_date=start_date,
            end_date=end_date,
            crown=crown,
            sheet_count=sheet_count,
            rate=rate,
            post_class=post_class,
        )
        notify_db_session.session.add(rate)
        notify_db_session.session.commit()
        created_letter_rates.append(rate.id)
        return rate

    yield _sample_letter_rate

    # Teardown
    stmt = delete(LetterRate).where(LetterRate.id.in_(created_letter_rates))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


@pytest.fixture
def sample_service_data_retention(notify_db_session):
    created_service_data_retention = []

    def _sample_service_data_retention(service, notification_type='sms', days_of_retention=3):
        # commits ServiceDataRetention
        data_retention = insert_service_data_retention(
            service_id=service.id, notification_type=notification_type, days_of_retention=days_of_retention
        )

        created_service_data_retention.append(data_retention.id)
        return data_retention

    yield _sample_service_data_retention

    # Teardown
    stmt = delete(ServiceDataRetention).where(ServiceDataRetention.id.in_(created_service_data_retention))
    notify_db_session.session.execute(stmt)
    notify_db_session.session.commit()


############################################################################
# The following dynamodb fixtures are for the Comp and Pen integration
############################################################################
@pytest.fixture
def dynamodb_mock():
    """
    Mock the DynamoDB table used for the Comp and Pen integration.
    """

    bip_table_vars = {
        'TableName': 'TestTable',
        'AttributeDefinitions': [
            {
                'AttributeName': 'participant_id',
                'AttributeType': 'N',
            },
            {
                'AttributeName': 'payment_id',
                'AttributeType': 'N',
            },
            {
                'AttributeName': 'is_processed',
                'AttributeType': 'S',
            },
        ],
        'KeySchema': [
            {'AttributeName': 'participant_id', 'KeyType': 'HASH'},
            {'AttributeName': 'payment_id', 'KeyType': 'RANGE'},
        ],
        'GlobalSecondaryIndexes': [
            {
                'IndexName': 'is-processed-index',
                'KeySchema': [{'AttributeName': 'is_processed', 'KeyType': 'HASH'}],
                'Projection': {
                    'ProjectionType': 'ALL',
                },
            },
        ],
        'BillingMode': 'PAY_PER_REQUEST',
    }
    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        # Create a mock DynamoDB table
        table = dynamodb.create_table(**bip_table_vars)

        # Wait for table to be created
        table.meta.client.get_waiter('table_exists').wait(TableName='TestTable')

        yield table


@pytest.fixture
def sample_dynamodb_insert(dynamodb_mock):
    items_inserted = []

    def _dynamodb_insert(items_to_insert: list):
        with dynamodb_mock.batch_writer() as batch:
            for item in items_to_insert:
                batch.put_item(Item=item)
                items_inserted.append(item)

    yield _dynamodb_insert

    # delete the items added
    for item in items_inserted:
        dynamodb_mock.delete_item(Key={'participant_id': item['participant_id'], 'payment_id': item['payment_id']})


@pytest.fixture(scope='function')
def mock_va_profile_client(mocker, notify_api):
    with notify_api.app_context():
        mock_logger = mocker.Mock()
        mock_ssl_key_path = 'some_key.pem'
        mock_ssl_cert_path = 'some_cert.pem'
        mock_statsd_client = mocker.Mock()
        mock_va_profile_token = mocker.Mock()

        client = VAProfileClient()
        client.init_app(
            logger=mock_logger,
            va_profile_url=MOCK_VA_PROFILE_URL,
            ssl_cert_path=mock_ssl_cert_path,
            ssl_key_path=mock_ssl_key_path,
            va_profile_token=mock_va_profile_token,
            statsd_client=mock_statsd_client,
        )

        return client


@pytest.fixture(scope='function')
def mock_va_profile_response():
    with open('tests/app/va/va_profile/mock_response.json', 'r') as f:
        return json.load(f)


@pytest.fixture
def x_minutes_ago():
    """Generate a timestamp in the past.

    Helper to make sure timestamps are sufficiently different

    Returns:
        datetime: 5 minutes ago, no timezone
    """

    # Database does not store tzinfo, so this has to be stripped for comparison purposes
    def _wrapper(x: int = 5):
        return (datetime.now(timezone.utc) - timedelta(minutes=x)).replace(tzinfo=None)

    yield _wrapper


#######################################################################################################################
#                                                                                                                     #
#                                                 SESSION-SCOPED                                                      #
#                                                                                                                     #
#######################################################################################################################

# These exist because a few tests are expecting VA Notify-specific resources to exist. Attempting to utilize them with
# function-scoped fixtures leads to race conditions.


@pytest.fixture(scope='session')
def sample_notify_service_user_session(
    notify_db, sample_service_session, sample_service_email_reply_to_session, sample_user_session
):
    u_id = current_app.config['NOTIFY_USER_ID']
    s_id = current_app.config['NOTIFY_SERVICE_ID']

    def _wrapper():
        # We only want these created if they are not already made. This was session-scoped before
        user = notify_db.session.get(User, u_id) or sample_user_session(user_id=u_id)

        service = notify_db.session.get(Service, s_id) or sample_service_session(
            service_name='Notify Service', email_from='notify.service', user=user, service_id=s_id
        )
        sample_service_email_reply_to_session(service)
        return service, user

    yield _wrapper
    # Teardown not required


@pytest.fixture(scope='session')
def sample_service_session(notify_db, sample_user_session):
    created_service_ids: list = []

    def _wrapper(*args, **kwargs):
        # We do not want create_service to create users because it does not clean them up
        if len(args) == 0 and 'user' not in kwargs:
            kwargs['user'] = sample_user_session()

        # TODO 1635: Fix issue with history -- duplicate key value violates unique constraint "services_history_pkey"
        service: Service = create_service(*args, **kwargs)

        # The session is different (dao) so we can't just use save the
        # session object for deletion. Save the ID, and query it later.
        created_service_ids.append(service.id)
        return service

    yield _wrapper
    service_cleanup(created_service_ids, notify_db.session)


@pytest.fixture(scope='session')
def sample_service_email_reply_to_session(notify_db, sample_service_session):
    service_email_reply_to_ids = []

    def _wrapper(service=None, **kwargs):
        data = {'service': service or sample_service_session(), 'email_address': 'vanotify@va.gov', 'is_default': True}
        service_email_reply_to = ServiceEmailReplyTo(**data)

        notify_db.session.add(service_email_reply_to)
        notify_db.session.commit()

        service_email_reply_to_ids.append(service_email_reply_to.id)
        return service_email_reply_to

    yield _wrapper

    # Teardown
    stmt = delete(ServiceEmailReplyTo).where(ServiceEmailReplyTo.id.in_(service_email_reply_to_ids))
    notify_db.session.execute(stmt)
    notify_db.session.commit()


@pytest.fixture(scope='session')
def sample_user_session(notify_db):
    created_user_ids = []

    def _sample_user(*args, **kwargs):
        # Cannot set platform admin when creating a user (schema)
        user = create_user(*args, **kwargs)
        created_user_ids.append(user.id)
        return user

    yield _sample_user

    user_cleanup(created_user_ids, notify_db.session)
