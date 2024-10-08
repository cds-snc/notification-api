import json
import random
from app import db
from app.dao.email_branding_dao import dao_create_email_branding
from app.dao.inbound_sms_dao import dao_create_inbound_sms
from app.dao.invited_org_user_dao import save_invited_org_user
from app.dao.invited_user_dao import save_invited_user
from app.dao.jobs_dao import dao_create_job
from app.dao.notifications_dao import dao_create_notification, dao_created_scheduled_notification
from app.dao.organisation_dao import dao_create_organisation
from app.dao.permissions_dao import permission_dao
from app.dao.service_callback_api_dao import save_service_callback_api
from app.dao.service_data_retention_dao import insert_service_data_retention
from app.dao.service_permissions_dao import dao_add_service_permission
from app.dao.service_sms_sender_dao import dao_update_service_sms_sender
from app.dao.services_dao import dao_create_service, dao_add_user_to_service
from app.dao.templates_dao import dao_create_template, dao_update_template
from app.dao.dao_utils import transactional, version_class
from app.model import User
from app.models import (
    ApiKey,
    DailySortedLetter,
    InboundSms,
    InboundNumber,
    Job,
    Notification,
    EmailBranding,
    Organisation,
    Permission,
    Rate,
    Service,
    ServiceEmailReplyTo,
    ServiceCallback,
    ServiceLetterContact,
    ScheduledNotification,
    ServicePermission,
    ServiceSmsSender,
    ServiceWhitelist,
    Template,
    EMAIL_TYPE,
    MOBILE_TYPE,
    SMS_TYPE,
    LETTER_TYPE,
    KEY_TYPE_NORMAL,
    AnnualBilling,
    InvitedOrganisationUser,
    FactBilling,
    FactNotificationStatus,
    Complaint,
    InvitedUser,
    TemplateFolder,
    Domain,
    NotificationHistory,
    RecipientIdentifier,
    NOTIFICATION_STATUS_TYPES_COMPLETED,
    DELIVERY_STATUS_CALLBACK_TYPE,
    WEBHOOK_CHANNEL_TYPE,
)
from datetime import datetime, date
from sqlalchemy import select, or_
from sqlalchemy.orm.attributes import flag_dirty
from uuid import UUID, uuid4


def create_user(
    mobile_number='+16502532222',
    email=None,
    state='active',
    user_id=None,
    identity_provider_user_id=None,
    name='Test User',
    blocked=False,
    platform_admin=False,
    check_if_user_exists=False,
    idp_name=None,
    idp_id=None,
):
    user = None
    if check_if_user_exists:
        # Returns None if not found
        user = db.session.scalar(select(User).where(or_(User.email_address == email, User.id == user_id)))

    if user is None:
        data = {
            'id': user_id or uuid4(),
            'name': name,
            # This is a unique, non-nullable field.
            'email_address': email if email is not None else f'create_user_{uuid4()}@va.gov',
            'password': 'password',
            'password_changed_at': datetime.utcnow(),
            # This is a unique, nullable field.
            'identity_provider_user_id': identity_provider_user_id,
            'mobile_number': mobile_number,
            'state': state,
            'blocked': blocked,
            'platform_admin': platform_admin,
            'idp_name': idp_name,
            'idp_id': idp_id,
        }

        user = transactional_save_user(User(**data))

    return user


def transactional_save_user(user: User) -> User:
    try:
        db.session.add(user)
        db.session.commit()
    except Exception:
        # Without the rollback some tests fail because they are supposed to raise DB exceptions to trigger rollbacks
        db.session.rollback()
        raise

    return user


def create_permissions(user, service, *permissions):
    permissions = [Permission(service_id=service.id, user_id=user.id, permission=p) for p in permissions]

    permission_dao.set_user_service_permission(user, service, permissions, _commit=True)


def create_service(
    user=None,
    service_name='',
    service_id=None,
    restricted=False,
    count_as_live=True,
    service_permissions=[EMAIL_TYPE, SMS_TYPE],
    research_mode=False,
    active=True,
    email_from='',
    prefix_sms=False,
    message_limit=1000,
    organisation_type='other',
    check_if_service_exists=False,
    go_live_user=None,
    go_live_at=None,
    crown=True,
    organisation=None,
    smtp_user=None,
):
    if check_if_service_exists:
        stmt = select(Service).where(Service.name == service_name)
        service = db.session.scalars(stmt).first()
    if (not check_if_service_exists) or (check_if_service_exists and not service):
        service = Service(
            name=service_name or uuid4(),
            message_limit=message_limit,
            restricted=restricted,
            email_from=email_from if email_from else service_name.lower().replace(' ', '.'),
            created_by=user if user else create_user(email=f'create_service_{uuid4()}@va.gov'),
            prefix_sms=prefix_sms,
            organisation_type=organisation_type,
            go_live_user=go_live_user,
            go_live_at=go_live_at,
            crown=crown,
            smtp_user=smtp_user,
        )
        dao_create_service(service, service.created_by, service_id, service_permissions=service_permissions)

        service.active = active
        service.research_mode = research_mode
        service.count_as_live = count_as_live
    else:
        if user and user not in service.users:
            dao_add_user_to_service(service, user)

    return service


@transactional
@version_class(Service)
def version_service(
    service,
):
    # version_class requires something in the session to flush, so flag service as dirty
    flag_dirty(service)


@transactional
@version_class(ApiKey)
def version_api_key(
    api_key,
):
    # version_class requires something in the session to flush, so flag service as dirty
    flag_dirty(api_key)


def create_service_with_inbound_number(inbound_number='1234567', *args, **kwargs):
    service = create_service(*args, **kwargs)

    stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
    sms_sender = db.session.scalars(stmt).first()
    inbound = create_inbound_number(number=inbound_number)
    dao_update_service_sms_sender(
        service_id=service.id,
        service_sms_sender_id=sms_sender.id,
        sms_sender=inbound_number,
        inbound_number_id=inbound.id,
    )

    return service


def create_service_with_defined_sms_sender(sms_sender_value='1234567', *args, **kwargs):
    service = create_service(*args, **kwargs)

    stmt = select(ServiceSmsSender).where(ServiceSmsSender.service_id == service.id)
    sms_sender = db.session.scalars(stmt).first()
    dao_update_service_sms_sender(
        service_id=service.id, service_sms_sender_id=sms_sender.id, is_default=True, sms_sender=sms_sender_value
    )

    return service


def create_template(
    service,
    template_type=SMS_TYPE,
    template_name=None,
    subject='Template subject',
    content='Dear Sir/Madam, Hello. Yours Truly, The Government.',
    reply_to=None,
    hidden=False,
    archived=False,
    folder=None,
    postage=None,
    process_type='normal',
    reply_to_email=None,
    onsite_notification=False,
    communication_item_id=None,
):
    data = {
        'name': template_name or '{} Template Name'.format(template_type),
        'template_type': template_type,
        'content': content,
        'service': service,
        'created_by': service.created_by,
        'reply_to': reply_to,
        'hidden': hidden,
        'folder': folder,
        'process_type': process_type,
        'communication_item_id': communication_item_id,
        'reply_to_email': reply_to_email,
        'onsite_notification': onsite_notification,
    }
    if template_type == LETTER_TYPE:
        data['postage'] = postage or 'second'
    if template_type != SMS_TYPE:
        data['subject'] = subject
    template = Template(**data)
    dao_create_template(template)

    if archived:
        template.archived = archived
        dao_update_template(template)

    return template


def create_notification(  # noqa: C901
    template=None,
    job=None,
    job_row_number=None,
    to_field=None,
    status='created',
    status_reason=None,
    reference=None,
    created_at=None,
    sent_at=None,
    updated_at=None,
    billable_units=1,
    segments_count=0,
    cost_in_millicents=0.000,
    personalisation=None,
    api_key=None,
    key_type=KEY_TYPE_NORMAL,
    sent_by=None,
    client_reference=None,
    rate_multiplier=None,
    international=False,
    phone_prefix=None,
    scheduled_for=None,
    normalised_to=None,
    one_off=False,
    reply_to_text=None,
    created_by_id=None,
    postage=None,
    recipient_identifiers=None,
    billing_code=None,
    sms_sender_id=None,
    callback_url=None,
):
    assert job or template
    if job:
        template = job.template

    if created_at is None:
        created_at = datetime.utcnow()

    if to_field is None:
        to_field = '+16502532222' if template.template_type == SMS_TYPE else 'test@example.com'

    if status != 'created':
        sent_at = sent_at or datetime.utcnow()
        updated_at = updated_at or datetime.utcnow()

    if not one_off and (job is None and api_key is None):
        # we didn't specify in test - lets create it
        stmt = select(ApiKey).where(ApiKey.service == template.service, ApiKey.key_type == key_type)
        api_key = db.session.scalar(stmt)
        if not api_key:
            api_key = create_api_key(template.service, key_type=key_type)

    if template.template_type == 'letter' and postage is None:
        postage = 'second'

    data = {
        'id': uuid4(),
        'to': to_field,
        'job_id': job and job.id,
        'job': job,
        'service_id': template.service.id,
        'service': template.service,
        'template_id': template.id,
        'template_version': template.version,
        'status': status,
        'status_reason': status_reason,
        'reference': reference,
        'created_at': created_at,
        'sent_at': sent_at,
        'billable_units': billable_units,
        'segments_count': segments_count,
        'cost_in_millicents': cost_in_millicents,
        'personalisation': personalisation,
        'notification_type': template.template_type,
        'api_key': api_key,
        'api_key_id': api_key and api_key.id,
        'key_type': api_key.key_type if api_key else key_type,
        'sent_by': sent_by,
        'updated_at': updated_at,
        'client_reference': client_reference,
        'job_row_number': job_row_number,
        'rate_multiplier': rate_multiplier,
        'international': international,
        'phone_prefix': phone_prefix,
        'normalised_to': normalised_to,
        'reply_to_text': reply_to_text,
        'created_by_id': created_by_id,
        'postage': postage,
        'billing_code': billing_code,
        'sms_sender_id': sms_sender_id,
        'callback_url': callback_url,
    }
    notification = Notification(**data)

    if recipient_identifiers:
        for recipient_identifier in recipient_identifiers:
            _recipient_identifier = RecipientIdentifier(
                notification_id=notification.id,
                id_type=recipient_identifier['id_type'],
                id_value=recipient_identifier['id_value'],
            )
            notification.recipient_identifiers.set(_recipient_identifier)

    dao_create_notification(notification)
    if scheduled_for:
        scheduled_notification = ScheduledNotification(
            id=uuid4(),
            notification_id=notification.id,
            scheduled_for=datetime.strptime(scheduled_for, '%Y-%m-%d %H:%M'),
        )
        if status != 'created':
            scheduled_notification.pending = False
        dao_created_scheduled_notification(scheduled_notification)

    return notification


def create_notification_history(
    template=None,
    job=None,
    job_row_number=None,
    status='created',
    reference=None,
    created_at=None,
    sent_at=None,
    updated_at=None,
    billable_units=1,
    segments_count=1,
    cost_in_millicents=0.001,
    api_key=None,
    key_type=KEY_TYPE_NORMAL,
    sent_by=None,
    client_reference=None,
    rate_multiplier=None,
    international=False,
    phone_prefix=None,
    created_by_id=None,
    postage=None,
):
    assert job or template
    if job:
        template = job.template

    if created_at is None:
        created_at = datetime.utcnow()

    if status != 'created':
        sent_at = sent_at or datetime.utcnow()
        updated_at = updated_at or datetime.utcnow()

    if template.template_type == 'letter' and postage is None:
        postage = 'second'

    data = {
        'id': uuid4(),
        'job_id': job and job.id,
        'job': job,
        'service_id': template.service.id,
        'service': template.service,
        'template_id': template.id,
        'template_version': template.version,
        'status': status,
        'reference': reference,
        'created_at': created_at,
        'sent_at': sent_at,
        'billable_units': billable_units,
        'segments_count': segments_count,
        'cost_in_millicents': cost_in_millicents,
        'notification_type': template.template_type,
        'api_key': api_key,
        'api_key_id': api_key and api_key.id,
        'key_type': api_key.key_type if api_key else key_type,
        'sent_by': sent_by,
        'updated_at': updated_at,
        'client_reference': client_reference,
        'job_row_number': job_row_number,
        'rate_multiplier': rate_multiplier,
        'international': international,
        'phone_prefix': phone_prefix,
        'created_by_id': created_by_id,
        'postage': postage,
    }
    notification_history = NotificationHistory(**data)
    db.session.add(notification_history)
    db.session.commit()

    return notification_history


def create_job(
    template,
    notification_count=1,
    created_at=None,
    job_status='pending',
    scheduled_for=None,
    processing_started=None,
    original_file_name='some.csv',
    archived=False,
):
    data = {
        'id': uuid4(),
        'service_id': template.service_id,
        'service': template.service,
        'template_id': template.id,
        'template_version': template.version,
        'original_file_name': original_file_name,
        'notification_count': notification_count,
        'created_at': created_at or datetime.utcnow(),
        'created_by': template.created_by,
        'job_status': job_status,
        'scheduled_for': scheduled_for,
        'processing_started': processing_started,
        'archived': archived,
    }
    job = Job(**data)
    dao_create_job(job)
    return job


def create_service_permission(service_id, permission=EMAIL_TYPE):
    dao_add_service_permission(service_id if service_id else create_service().id, permission)

    stmt = select(ServicePermission)
    service_permissions = db.session.scalars(stmt).all()

    return service_permissions


def create_inbound_sms(
    service,
    notify_number=None,
    user_number='+16502532222',
    provider_date=None,
    provider_reference=None,
    content='Hello',
    provider='mmg',
    created_at=None,
):
    if not service.inbound_numbers:
        create_inbound_number(
            # create random inbound number
            notify_number or '1{:10}'.format(random.randint(0, 1e9 - 1)),  # nosec
            provider=provider,
            service_id=service.id,
        )

    inbound = InboundSms(
        service=service,
        created_at=created_at or datetime.utcnow(),
        notify_number=service.inbound_numbers[0].number,
        user_number=user_number,
        provider_date=provider_date or datetime.utcnow(),
        provider_reference=provider_reference or 'foo',
        content=content,
        provider=provider,
    )
    dao_create_inbound_sms(inbound)
    return inbound


def create_service_callback_api(  # nosec
    service,
    url='https://something.com',
    bearer_token='some_super_secret',
    callback_type=DELIVERY_STATUS_CALLBACK_TYPE,
    notification_statuses=NOTIFICATION_STATUS_TYPES_COMPLETED,
    callback_channel=WEBHOOK_CHANNEL_TYPE,
    include_provider_payload=False,
):
    if callback_type == DELIVERY_STATUS_CALLBACK_TYPE:
        service_callback_api = ServiceCallback(
            service_id=service.id,
            url=url,
            bearer_token=bearer_token,
            updated_by_id=service.users[0].id,
            callback_type=callback_type,
            notification_statuses=notification_statuses,
            callback_channel=callback_channel,
            include_provider_payload=include_provider_payload,
        )
    else:
        service_callback_api = ServiceCallback(
            service_id=service.id,
            url=url,
            bearer_token=bearer_token,
            updated_by_id=service.users[0].id,
            callback_type=callback_type,
            callback_channel=callback_channel,
            include_provider_payload=include_provider_payload,
        )
    save_service_callback_api(service_callback_api)
    return service_callback_api


def create_email_branding(colour='blue', logo='test_x2.png', name='test_org_1', text='DisplayName'):
    data = {
        'colour': colour,
        'logo': logo,
        'name': name,
        'text': text,
    }
    email_branding = EmailBranding(**data)
    dao_create_email_branding(email_branding)

    return email_branding


def create_rate(start_date, value, notification_type):
    rate = Rate(id=uuid4(), valid_from=start_date, rate=value, notification_type=notification_type)
    db.session.add(rate)
    db.session.commit()
    return rate


def create_api_key(service, key_type=KEY_TYPE_NORMAL, key_name=None, expired=False):
    id_ = str(uuid4())

    name = key_name or f'{key_type} api key {id_}'

    data = {
        'service': service,
        'name': name,
        'created_by': service.created_by,
        'key_type': key_type,
        'id': id_,
        'secret': str(uuid4()),
    }

    if expired:
        data['expiry_date'] = datetime.utcnow()

    api_key = ApiKey(**data)
    db.session.add(api_key)
    db.session.commit()
    return api_key


def create_inbound_number(
    number,
    provider='ses',
    active=True,
    service_id=None,
    url_endpoint=None,
    self_managed=False,
    auth_parameter=None,
):
    inbound_number = InboundNumber(
        id=uuid4(),
        number=number,
        provider=provider,
        active=active,
        service_id=service_id,
        url_endpoint=url_endpoint,
        self_managed=self_managed,
        auth_parameter=auth_parameter,
    )
    db.session.add(inbound_number)
    db.session.commit()
    return inbound_number


def create_reply_to_email(service, email_address, is_default=True, archived=False):
    data = {
        'service': service,
        'email_address': email_address,
        'is_default': is_default,
        'archived': archived,
    }
    reply_to = ServiceEmailReplyTo(**data)

    db.session.add(reply_to)
    db.session.commit()

    return reply_to


def create_service_sms_sender(
    service, sms_sender, is_default=True, inbound_number_id=None, archived=False, sms_sender_specifics={}
):
    data = {
        'service_id': service.id,
        'sms_sender': sms_sender,
        'is_default': is_default,
        'inbound_number_id': inbound_number_id,
        'archived': archived,
        'sms_sender_specifics': sms_sender_specifics,
    }
    service_sms_sender = ServiceSmsSender(**data)

    db.session.add(service_sms_sender)
    db.session.commit()

    return service_sms_sender


def create_letter_contact(service, contact_block, is_default=True, archived=False):
    data = {
        'service': service,
        'contact_block': contact_block,
        'is_default': is_default,
        'archived': archived,
    }
    letter_content = ServiceLetterContact(**data)

    db.session.add(letter_content)
    db.session.commit()

    return letter_content


def create_annual_billing(service_id, free_sms_fragment_limit, financial_year_start):
    annual_billing = AnnualBilling(
        service_id=service_id,
        free_sms_fragment_limit=free_sms_fragment_limit,
        financial_year_start=financial_year_start,
    )
    db.session.add(annual_billing)
    db.session.commit()

    return annual_billing


def create_domain(domain, organisation_id):
    domain = Domain(domain=domain, organisation_id=organisation_id)

    db.session.add(domain)
    db.session.commit()

    return domain


def create_organisation(name='test_org_1', active=True, organisation_type=None, domains=None):
    stmt = select(Organisation).where(Organisation.name == name)
    organisation = db.session.scalars(stmt).first()

    if organisation:
        organisation.active = active
        organisation.organisation_type = organisation_type
    else:
        data = {
            'name': name,
            'active': active,
            'organisation_type': organisation_type,
        }
        organisation = Organisation(**data)
        dao_create_organisation(organisation)

    for domain in domains or []:
        create_domain(domain, organisation.id)

    return organisation


def create_invited_org_user(organisation, invited_by, email_address='invite@example.com'):
    invited_org_user = InvitedOrganisationUser(
        email_address=email_address,
        invited_by=invited_by,
        organisation=organisation,
    )
    save_invited_org_user(invited_org_user)
    return invited_org_user


def create_daily_sorted_letter(
    billing_day=date(2018, 1, 18), file_name='Notify-20180118123.rs.txt', unsorted_count=0, sorted_count=0
):
    daily_sorted_letter = DailySortedLetter(
        billing_day=billing_day, file_name=file_name, unsorted_count=unsorted_count, sorted_count=sorted_count
    )

    db.session.add(daily_sorted_letter)
    db.session.commit()

    return daily_sorted_letter


def create_ft_billing(
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
        service = create_service()
    if not template:
        template = create_template(service=service, template_type=notification_type)

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
    db.session.add(data)
    db.session.commit()
    return data


def create_ft_notification_status(
    utc_date,
    notification_type='sms',
    service=None,
    template=None,
    job=None,
    key_type='normal',
    notification_status='delivered',
    status_reason='',
    count=1,
):
    if job:
        template = job.template

    if template:
        service = template.service
        notification_type = template.template_type
    else:
        if not service:
            service = create_service()
        template = create_template(service=service, template_type=notification_type)

    data = FactNotificationStatus(
        bst_date=utc_date,
        template_id=template.id,
        service_id=service.id,
        job_id=job.id if job else UUID(int=0),
        notification_type=notification_type,
        key_type=key_type,
        notification_status=notification_status,
        status_reason=status_reason,
        notification_count=count,
    )
    db.session.add(data)
    db.session.commit()
    return data


def create_service_whitelist(service, email_address=None, mobile_number=None):
    if email_address:
        whitelisted_user = ServiceWhitelist.from_string(service.id, EMAIL_TYPE, email_address)
    elif mobile_number:
        whitelisted_user = ServiceWhitelist.from_string(service.id, MOBILE_TYPE, mobile_number)
    else:
        whitelisted_user = ServiceWhitelist.from_string(service.id, EMAIL_TYPE, 'whitelisted_user@digital.gov.uk')

    db.session.add(whitelisted_user)
    db.session.commit()
    return whitelisted_user


def create_complaint(service=None, notification=None, created_at=None):
    if not service:
        service = create_service()
    if not notification:
        template = create_template(service=service, template_type='email')
        notification = create_notification(template=template)

    complaint = Complaint(
        notification_id=notification.id,
        service_id=service.id,
        feedback_id=str(uuid4()),
        complaint_type='abuse',
        complaint_date=datetime.utcnow(),
        created_at=created_at if created_at else datetime.now(),
    )
    db.session.add(complaint)
    db.session.commit()
    return complaint


def ses_complaint_callback_malformed_message_id():
    return {
        'Signature': 'bb',
        'SignatureVersion': '1',
        'MessageAttributes': {},
        'MessageId': '98c6e927-af5d-5f3b-9522-bab736f2cbde',
        'UnsubscribeUrl': 'https://sns.eu-west-1.amazonaws.com',
        'TopicArn': 'arn:ses_notifications',
        'Type': 'Notification',
        'Timestamp': '2018-06-05T14:00:15.952Z',
        'Subject': None,
        'Message': '{"eventType":"Complaint","complaint":{"complainedRecipients":[{"emailAddress":"recipient1@example.com"}],"timestamp":"2018-06-05T13:59:58.000Z","feedbackId":"ses_feedback_id"},"mail":{"timestamp":"2018-06-05T14:00:15.950Z","source":"\\"Some Service\\" <someservicenotifications.service.gov.uk>","sourceArn":"arn:identity/notifications.service.gov.uk","sourceIp":"52.208.24.161","sendingAccountId":"888450439860","badMessageId":"ref1","destination":["recipient1@example.com"]}}',  # noqa
        'SigningCertUrl': 'https://sns.pem',
    }


def ses_complaint_callback_with_missing_complaint_type():
    """
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/notification-contents.html#complaint-object
    """
    return {
        'Signature': 'bb',
        'SignatureVersion': '1',
        'MessageAttributes': {},
        'MessageId': '98c6e927-af5d-5f3b-9522-bab736f2cbde',
        'UnsubscribeUrl': 'https://sns.eu-west-1.amazonaws.com',
        'TopicArn': 'arn:ses_notifications',
        'Type': 'Notification',
        'Timestamp': '2018-06-05T14:00:15.952Z',
        'Subject': None,
        'Message': '{"eventType":"Complaint","complaint":{"complainedRecipients":[{"emailAddress":"recipient1@example.com"}],"timestamp":"2018-06-05T13:59:58.000Z","feedbackId":"ses_feedback_id"},"mail":{"timestamp":"2018-06-05T14:00:15.950Z","source":"\\"Some Service\\" <someservicenotifications.service.gov.uk>","sourceArn":"arn:identity/notifications.service.gov.uk","sourceIp":"52.208.24.161","sendingAccountId":"888450439860","messageId":"ref1","destination":["recipient1@example.com"]}}',  # noqa
        'SigningCertUrl': 'https://sns.pem',
    }


def ses_complaint_callback():
    """
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/notification-contents.html#complaint-object
    """
    return {
        'Signature': 'bb',
        'SignatureVersion': '1',
        'MessageAttributes': {},
        'MessageId': '98c6e927-af5d-5f3b-9522-bab736f2cbde',
        'UnsubscribeUrl': 'https://sns.eu-west-1.amazonaws.com',
        'TopicArn': 'arn:ses_notifications',
        'Type': 'Notification',
        'Timestamp': '2018-06-05T14:00:15.952Z',
        'Subject': None,
        'Message': '{"eventType":"Complaint","complaint":{"complaintFeedbackType": "abuse", "complainedRecipients":[{"emailAddress":"recipient1@example.com"}],"timestamp":"2018-06-05T13:59:58.000Z","feedbackId":"ses_feedback_id"},"mail":{"timestamp":"2018-06-05T14:00:15.950Z","source":"\\"Some Service\\" <someservicenotifications.service.gov.uk>","sourceArn":"arn:identity/notifications.service.gov.uk","sourceIp":"52.208.24.161","sendingAccountId":"888450439860","messageId":"ref1","destination":["recipient1@example.com"]}}',  # noqa
        'SigningCertUrl': 'https://sns.pem',
    }


def ses_smtp_complaint_callback(feedback_id: str = '0100017058b9253c-10257f1d-9a33-4352-8b34-f6c9f0bd2c74-000000'):
    """
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/notification-contents.html#complaint-object
    """
    return {
        'Signature': 'bb',
        'SignatureVersion': '1',
        'MessageAttributes': {},
        'MessageId': '98c6e927-af5d-5f3b-9522-bab736f2cbde',
        'UnsubscribeUrl': 'https://sns.eu-west-1.amazonaws.com',
        'TopicArn': 'arn:ses_notifications',
        'Type': 'Notification',
        'Timestamp': '2018-06-05T14:00:15.952Z',
        'Subject': None,
        'Message': '{"eventType":"Complaint","complaint":{"complaintSubType":null,"complainedRecipients":[{"emailAddress":"complaint@simulator.amazonses.com"}],"timestamp":"2020-02-18T14:34:53.000Z","feedbackId":"0100017058b9253c-10257f1d-9a33-4352-8b34-f6c9f0bd2c74-000000","userAgent":"Amazon SES Mailbox Simulator","complaintFeedbackType":"abuse"},"mail":{"timestamp":"2020-02-18T14:34:52.000Z","source":"test@smtp_user","sourceArn":"arn:aws:ses:us-east-1:248983331664:identity/smtp_user","sourceIp":"","sendingAccountId":"","messageId":"0100017058b9230e-6bd4bb0b-0d37-4690-97c7-ca25b4b40755-000000","destination":["complaint@simulator.amazonses.com"],"headersTruncated":false,"headers":[{"name":"Received","value":"from Maxs-MacBook-Pro.local (CPE704ca52f06e7-CMf81d0fa26620.cpe.net.cable.rogers.com []) by email-smtp.amazonaws.com with SMTP (SimpleEmailService-d-P4XJ6SAG2) id Ayj6eL5Zy9bZQqaeWP88 for complaint@simulator.amazonses.com; Tue, 18 Feb 2020 14:34:52 +0000 (UTC)"},{"name":"Content-Type","value":"multipart/alternative; boundary=\\"--_NmP-959c1f6221c7e029-Part_1\\""},{"name":"From","value":"Max Neuvians <test@smtp_user>"},{"name":"To","value":"complaint@simulator.amazonses.com"},{"name":"Subject","value":"Hello ✔"},{"name":"Message-ID","value":"<b0c7ad2d-6eb6-04e6-797f-e22d63781b20@smtp_user>"},{"name":"Date","value":"Tue, 18 Feb 2020 14:34:52 +0000"},{"name":"MIME-Version","value":"1.0"}],"commonHeaders":{"from":["Max Neuvians <test@smtp_user>"],"date":"Tue, 18 Feb 2020 14:34:52 +0000","to":["complaint@simulator.amazonses.com"],"messageId":"<b0c7ad2d-6eb6-04e6-797f-e22d63781b20@smtp_user>","subject":"Hello ✔"}}}'.replace(
            '0100017058b9253c-10257f1d-9a33-4352-8b34-f6c9f0bd2c74-000000', feedback_id
        ),  # noqa
        'SigningCertUrl': 'https://sns.pem',
    }


def ses_notification_callback():
    return (
        '{\n  "Type" : "Notification",\n  "MessageId" : "ref1",'
        '\n  "TopicArn" : "arn:aws:sns:eu-west-1:123456789012:testing",'
        '\n  "Message" : "{\\"eventType\\":\\"Delivery\\",'
        '\\"mail\\":{\\"timestamp\\":\\"2016-03-14T12:35:25.909Z\\",'
        '\\"source\\":\\"test@smtp_user\\",'
        '\\"sourceArn\\":\\"arn:aws:ses:eu-west-1:123456789012:identity/testing-notify\\",'
        '\\"sendingAccountId\\":\\"123456789012\\",'
        '\\"messageId\\":\\"ref1\\",'
        '\\"destination\\":[\\"testing@digital.cabinet-office.gov.uk\\"]},'
        '\\"delivery\\":{\\"timestamp\\":\\"2016-03-14T12:35:26.567Z\\",'
        '\\"processingTimeMillis\\":658,'
        '\\"recipients\\":[\\"testing@digital.cabinet-office.gov.uk\\"],'
        '\\"smtpResponse\\":\\"250 2.0.0 OK 1457958926 uo5si26480932wjc.221 - gsmtp\\",'
        '\\"reportingMTA\\":\\"a6-238.smtp-out.eu-west-1.amazonses.com\\"}}",'
        '\n  "Timestamp" : "2016-03-14T12:35:26.665Z",\n  "SignatureVersion" : "1",'
        '\n  "Signature" : "",'
        '\n  "SigningCertURL" : "https://sns.eu-west-1.amazonaws.com/SimpleNotificationService-bb750'
        'dd426d95ee9390147a5624348ee.pem",'
        '\n  "UnsubscribeURL" : "https://sns.eu-west-1.amazonaws.com/?Action=Unsubscribe&S'
        'subscriptionArn=arn:aws:sns:eu-west-1:302763885840:preview-emails:d6aad3ef-83d6-4cf3-a470-54e2e75916da"\n}'
    )


def ses_smtp_notification_callback():
    return {
        'Signature': 'bb',
        'SignatureVersion': '1',
        'MessageAttributes': {},
        'MessageId': '98c6e927-af5d-5f3b-9522-bab736f2cbde',
        'UnsubscribeUrl': 'https://sns.eu-west-1.amazonaws.com',
        'TopicArn': 'arn:ses_notifications',
        'Type': 'Notification',
        'Timestamp': '2018-06-05T14:00:15.952Z',
        'Subject': None,
        'Message': '{"eventType":"Delivery","mail":{"timestamp":"2020-02-18T14:34:53.070Z","source":"test@smtp_user","sourceArn":"arn:aws:ses:us-east-1:248983331664:identity/smtp_user","sourceIp":"","sendingAccountId":"248983331664","messageId":"0100017058b9230e-6bd4bb0b-0d37-4690-97c7-ca25b4b40755-000000","destination":["complaint@simulator.amazonses.com"],"headersTruncated":false,"headers":[{"name":"Received","value":"from Maxs-MacBook-Pro.local () by email-smtp.amazonaws.com with SMTP (SimpleEmailService-d-P4XJ6SAG2) id Ayj6eL5Zy9bZQqaeWP88 for complaint@simulator.amazonses.com; Tue, 18 Feb 2020 14:34:52 +0000 (UTC)"},{"name":"Content-Type","value":"multipart/alternative; boundary=\\"--_NmP-959c1f6221c7e029-Part_1\\""},{"name":"From","value":"Max Neuvians <test@smtp_user>"},{"name":"To","value":"complaint@simulator.amazonses.com"},{"name":"Subject","value":"Hello ✔"},{"name":"Message-ID","value":"<b0c7ad2d-6eb6-04e6-797f-e22d63781b20@smtp_user>"},{"name":"Date","value":"Tue, 18 Feb 2020 14:34:52 +0000"},{"name":"MIME-Version","value":"1.0"}],"commonHeaders":{"from":["Max Neuvians <test@smtp_user>"],"date":"Tue, 18 Feb 2020 14:34:52 +0000","to":["complaint@simulator.amazonses.com"],"messageId":"<b0c7ad2d-6eb6-04e6-797f-e22d63781b20@smtp_user>","subject":"Hello ✔"}},"delivery":{"timestamp":"2020-02-18T14:34:53.519Z","processingTimeMillis":449,"recipients":["complaint@simulator.amazonses.com"],"smtpResponse":"250 2.6.0 Message received","remoteMtaIp":"34.204.216.130","reportingMTA":"a8-90.smtp-out.amazonses.com"}}',  # noqa
        'SigningCertUrl': 'https://sns.pem',
    }


def ses_smtp_hard_bounce_callback(reference):
    return _ses_bounce_callback(reference, 'Permanent')


def ses_smtp_soft_bounce_callback(reference):
    return _ses_bounce_callback(reference, 'Temporary')


def _ses_bounce_callback(reference, bounce_type):
    ses_message_body = {
        'bounce': {
            'bounceSubType': 'General',
            'bounceType': bounce_type,
            'bouncedRecipients': [
                {
                    'action': 'failed',
                    'diagnosticCode': 'smtp; 550 5.1.1 user unknown',
                    'emailAddress': 'bounce@simulator.amazonses.com',
                    'status': '5.1.1',
                }
            ],
            'feedbackId': '0102015fc9e676fb-12341234-1234-1234-1234-9301e86a4fa8-000000',
            'remoteMtaIp': '123.123.123.123',
            'reportingMTA': 'dsn; a7-31.smtp-out.eu-west-1.amazonses.com',
            'timestamp': '2017-11-17T12:14:05.131Z',
        },
        'mail': {
            'commonHeaders': {
                'from': ['TEST <TEST@smtp_user>'],
                'subject': 'ses callback test',
                'to': ['bounce@simulator.amazonses.com'],
                'date': 'Tue, 18 Feb 2020 14:34:52 +0000',
            },
            'destination': ['bounce@simulator.amazonses.com'],
            'headers': [
                {'name': 'From', 'value': 'TEST <TEST@smtp_user>'},
                {'name': 'To', 'value': 'bounce@simulator.amazonses.com'},
                {'name': 'Subject', 'value': 'lambda test'},
                {'name': 'MIME-Version', 'value': '1.0'},
                {
                    'name': 'Content-Type',
                    'value': 'multipart/alternative; boundary="----=_Part_596529_2039165601.1510920843367"',
                },
            ],
            'headersTruncated': False,
            'messageId': reference,
            'sendingAccountId': '12341234',
            'source': 'TEST@smtp_user',
            'sourceArn': 'arn:aws:ses:eu-west-1:12341234:identity/smtp_user',
            'sourceIp': '0.0.0.1',
            'timestamp': '2017-11-17T12:14:03.000Z',
        },
        'eventType': 'Bounce',
    }
    return {
        'Type': 'Notification',
        'MessageId': '36e67c28-1234-1234-1234-2ea0172aa4a7',
        'TopicArn': 'arn:aws:sns:eu-west-1:12341234:ses_notifications',
        'Subject': None,
        'Message': json.dumps(ses_message_body),
        'Timestamp': '2017-11-17T12:14:05.149Z',
        'SignatureVersion': '1',
        'Signature': '[REDACTED]',  # noqa
        'SigningCertUrl': 'https://sns.eu-west-1.amazonaws.com/SimpleNotificationService-[REDACTED]].pem',
        'UnsubscribeUrl': 'https://sns.eu-west-1.amazonaws.com/?Action=Unsubscribe&SubscriptionArn=[REDACTED]]',
        'MessageAttributes': {},
    }


def create_service_data_retention(service, notification_type='sms', days_of_retention=3):
    data_retention = insert_service_data_retention(
        service_id=service.id, notification_type=notification_type, days_of_retention=days_of_retention
    )
    return data_retention


def create_invited_user(service=None, to_email_address=None):
    if service is None:
        service = create_service()
    if to_email_address is None:
        to_email_address = 'invited_user@digital.gov.uk'

    from_user = service.users[0]

    data = {
        'service': service,
        'email_address': to_email_address,
        'from_user': from_user,
        'permissions': 'send_messages,manage_service,manage_api_keys',
        'folder_permissions': [str(uuid4()), str(uuid4())],
    }
    invited_user = InvitedUser(**data)
    save_invited_user(invited_user)
    return invited_user


def create_template_folder(service, name='foo', parent=None):
    tf = TemplateFolder(name=name, service=service, parent=parent)
    db.session.add(tf)
    db.session.commit()
    return tf
