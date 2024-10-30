"""
This file declares marshmallow-sqlalchemy schemas used to serialize and deserialize objects.

https://marshmallow-sqlalchemy.readthedocs.io/en/latest/index.html#generate-marshmallow-schemas
"""

from app import ma, models
from app.constants import (
    CALLBACK_CHANNEL_TYPES,
    DELIVERY_STATUS_CALLBACK_TYPE,
    EMAIL_AUTH_TYPE,
    EMAIL_TYPE,
    LETTER_TYPE,
    NOTIFICATION_STATUS_TYPES_COMPLETED,
    SERVICE_PERMISSION_TYPES,
    SMS_TYPE,
)
from app.dao.communication_item_dao import get_communication_item
from app.dao.permissions_dao import permission_dao
from app.model import User
from app.models import (
    ServicePermission,
)
from app.provider_details import validate_providers
from app.utils import get_template_instance
from datetime import date, datetime, timedelta
from flask_marshmallow.fields import fields
from marshmallow import (
    post_load,
    ValidationError,
    validates,
    validates_schema,
    pre_load,
    pre_dump,
    post_dump,
    validate,
)
from marshmallow_sqlalchemy import field_for
from notifications_utils.recipients import (
    validate_email_address,
    InvalidEmailError,
    validate_phone_number,
    InvalidPhoneError,
    validate_and_format_phone_number,
)
from sqlalchemy.orm.exc import NoResultFound

DATE_FORMAT = '%Y-%m-%d %H:%M:%S.%f'


def _validate_positive_number(
    value,
    msg='Not a positive integer',
):
    try:
        page_int = int(value)
    except ValueError:
        raise ValidationError(msg)
    if page_int < 1:
        raise ValidationError(msg)


def _validate_datetime_not_more_than_96_hours_in_future(
    dte,
    msg='Date cannot be more than 96hrs in the future',
):
    if dte > datetime.utcnow() + timedelta(hours=96):
        raise ValidationError(msg)


def _validate_not_in_future(
    dte,
    msg='Date cannot be in the future',
):
    if dte > date.today():
        raise ValidationError(msg)


def _validate_not_in_past(
    dte,
    msg='Date cannot be in the past',
):
    if dte < date.today():
        raise ValidationError(msg)


def _validate_datetime_not_in_future(
    dte,
    msg='Date cannot be in the future',
):
    if dte > datetime.utcnow():
        raise ValidationError(msg)


def _validate_datetime_not_in_past(
    dte,
    msg='Date cannot be in the past',
):
    if dte < datetime.utcnow():
        raise ValidationError(msg)


class BaseSchema(ma.SQLAlchemyAutoSchema):
    def __init__(
        self,
        load_json=False,
        *args,
        **kwargs,
    ):
        self.load_json = load_json
        super(BaseSchema, self).__init__(*args, **kwargs)

    @post_load
    def make_instance(self, data, many=False, partial=False):
        """
        Deserialize data to an instance of the model. Update an existing row
        if specified in `self.instance` or loaded by primary key(s) in the data;
        else create a new row.
        :param data: Data to deserialize.
        """

        if self.load_json:
            return data
        return super(BaseSchema, self).make_instance(data)


class UserSchema(BaseSchema):
    permissions = fields.Method('user_permissions', dump_only=True)
    password_changed_at = field_for(User, 'password_changed_at', format=DATE_FORMAT)
    created_at = field_for(User, 'created_at', format=DATE_FORMAT)
    auth_type = field_for(User, 'auth_type')
    identity_provider_user_id = fields.String(required=False)

    class Meta:
        model = User
        exclude = (
            'updated_at',
            'created_at',
            'services',
            'organisations',
            '_password',
            'verify_codes',
            '_identity_provider_user_id',
        )
        strict = True
        load_instance = True

    def user_permissions(
        self,
        usr,
    ):
        retval = {}
        for x in permission_dao.get_permissions_by_user_id(usr.id):
            service_id = str(x.service_id)
            if service_id not in retval:
                retval[service_id] = []
            retval[service_id].append(x.permission)
        return retval

    @validates('name')
    def validate_name(
        self,
        value,
        **kwargs,
    ):
        if not value:
            raise ValidationError('Invalid name')

    @validates('email_address')
    def validate_email_address(
        self,
        value,
        **kwargs,
    ):
        try:
            validate_email_address(value)
        except InvalidEmailError as e:
            raise ValidationError(str(e))

    @validates('mobile_number')
    def validate_mobile_number(
        self,
        value,
        **kwargs,
    ):
        try:
            if value is not None:
                validate_phone_number(value, international=True)
        except InvalidPhoneError as error:
            raise ValidationError('Invalid phone number: {}'.format(error))


class UserUpdateAttributeSchema(BaseSchema):
    auth_type = field_for(User, 'auth_type')
    identity_provider_user_id = fields.String(required=False, allow_none=True)

    class Meta:
        model = User
        exclude = (
            'id',
            'updated_at',
            'created_at',
            'services',
            '_password',
            'verify_codes',
            'logged_in_at',
            'password_changed_at',
            'failed_login_count',
            'state',
            'platform_admin',
            '_identity_provider_user_id',
        )
        strict = True

    @validates('name')
    def validate_name(
        self,
        value,
        **kwargs,
    ):
        if not value:
            raise ValidationError('Invalid name')

    @validates('email_address')
    def validate_email_address(
        self,
        value,
        **kwargs,
    ):
        try:
            validate_email_address(value)
        except InvalidEmailError as e:
            raise ValidationError(str(e))

    @validates('mobile_number')
    def validate_mobile_number(
        self,
        value,
        **kwargs,
    ):
        try:
            if value is not None:
                validate_phone_number(value, international=True)
        except InvalidPhoneError as error:
            raise ValidationError('Invalid phone number: {}'.format(error))

    @validates_schema(pass_original=True)
    def check_unknown_fields(
        self,
        data,
        original_data,
        **kwargs,
    ):
        for key in original_data:
            if key not in self.fields:
                raise ValidationError('Unknown field name {}'.format(key))


class UserUpdatePasswordSchema(BaseSchema):
    class Meta:
        model = User
        only = 'password'
        strict = True

    @validates_schema(pass_original=True)
    def check_unknown_fields(
        self,
        data,
        original_data,
        **kwargs,
    ):
        for key in original_data:
            if key not in self.fields:
                raise ValidationError('Unknown field name {}'.format(key))


class ProviderDetailsSchema(BaseSchema):
    created_by = fields.Nested(UserSchema, only=['id', 'name', 'email_address'], dump_only=True)

    class Meta:
        model = models.ProviderDetails
        exclude = ('provider_rates',)
        strict = True


class ProviderDetailsHistorySchema(BaseSchema):
    created_by = fields.Nested(UserSchema, only=['id', 'name', 'email_address'], dump_only=True)

    class Meta:
        model = models.ProviderDetailsHistory
        strict = True


class ServiceSchema(BaseSchema):
    created_by = field_for(models.Service, 'created_by', required=True)
    organisation_type = field_for(models.Service, 'organisation_type')
    letter_logo_filename = None
    permissions = fields.Method('get_service_permissions', deserialize='set_service_permissions', allow_none=True)
    email_branding = field_for(models.Service, 'email_branding')
    organisation = field_for(models.Service, 'organisation')
    override_flag = False
    letter_contact_block = fields.Method(
        serialize='get_letter_contact', deserialize='set_letter_contact', allow_none=True
    )
    go_live_at = field_for(models.Service, 'go_live_at', format=DATE_FORMAT)
    email_provider_id = field_for(models.Service, 'email_provider_id')
    sms_provider_id = field_for(models.Service, 'sms_provider_id')

    def get_service_permissions(
        self,
        service,
    ):
        return [p.permission for p in service.permissions]

    def set_service_permissions(
        self,
        obj,
    ):
        return [ServicePermission(service_id=p.service_id, permission=p.permission) for p in obj]

    def get_letter_contact(
        self,
        service,
    ):
        return service.get_default_letter_contact()

    def set_letter_contact(
        self,
        obj,
    ):
        return str(obj)

    class Meta:
        model = models.Service
        exclude = (
            'updated_at',
            'created_at',
            'api_keys',
            'templates',
            'jobs',
            'service_sms_senders',
            'reply_to_email_addresses',
            'letter_contacts',
            'complaints',
            'inbound_sms',
        )
        strict = True
        load_instance = True
        include_relationships = True

    @validates('permissions')
    def validate_permissions(
        self,
        value,
        **kwargs,
    ):
        permissions = [v.permission for v in value]
        for p in permissions:
            if p not in SERVICE_PERMISSION_TYPES:
                raise ValidationError("Invalid Service Permission: '{}'".format(p))

        if len(set(permissions)) != len(permissions):
            duplicates = list(set([x for x in permissions if permissions.count(x) > 1]))
            raise ValidationError('Duplicate Service Permission: {}'.format(duplicates))

    @validates('email_provider_id')
    def validate_email_provider_id(
        self,
        value,
        **kwargs,
    ):
        if value and not validate_providers.is_provider_valid(value, EMAIL_TYPE):
            raise ValidationError(f'Invalid email_provider_id: {value}')

    @validates('sms_provider_id')
    def validate_sms_provider_id(
        self,
        value,
        **kwargs,
    ):
        if value and not validate_providers.is_provider_valid(value, SMS_TYPE):
            raise ValidationError(f'Invalid sms_provider_id: {value}')

    @validates('consent_to_research')
    def validate_consent_to_research(
        self,
        value,
        **kwargs,
    ):
        if value is not None and not isinstance(value, bool):
            raise ValidationError('Invalid consent_to_research')

    @pre_load()
    def format_for_data_model(
        self,
        in_data,
        **kwargs,
    ):
        if isinstance(in_data, dict) and 'permissions' in in_data:
            str_permissions = in_data['permissions']
            permissions = []
            for p in str_permissions:
                permission = ServicePermission(service_id=in_data['id'], permission=p)
                permissions.append(permission)

            in_data['permissions'] = permissions
        return in_data


class ServiceCallbackSchema(BaseSchema):
    created_at = field_for(models.ServiceCallback, 'created_at', format=DATE_FORMAT)

    class Meta:
        model = models.ServiceCallback
        fields = (
            'id',
            'service_id',
            'url',
            'notification_statuses',
            'updated_by_id',
            'created_at',
            'updated_at',
            'bearer_token',
            'callback_type',
            'callback_channel',
            'include_provider_payload',
        )
        load_only = ['_bearer_token', 'bearer_token']
        strict = True
        load_instance = True

    @validates_schema
    def validate_schema(
        self,
        data,
        **kwargs,
    ):
        if 'callback_type' in data and 'notification_statuses' in data:
            if data['callback_type'] != DELIVERY_STATUS_CALLBACK_TYPE and data['notification_statuses'] is not None:
                raise ValidationError(f"Callback type {data['callback_type']} should not have notification statuses")

        if 'callback_channel' in data and 'bearer_token' not in data:
            if data['callback_channel'] == 'webhook':
                raise ValidationError(f"Callback channel {data['callback_channel']} should have bearer_token")

    @validates('callback_channel')
    def validate_callback_channel(
        self,
        value,
        **kwargs,
    ):
        validator = validate.OneOf(choices=CALLBACK_CHANNEL_TYPES, error='Invalid callback channel')
        validator(value)

    @validates('notification_statuses')
    def validate_notification_statuses(
        self,
        value,
        **kwargs,
    ):
        validator = validate.ContainsOnly(
            choices=NOTIFICATION_STATUS_TYPES_COMPLETED, error='Invalid notification statuses'
        )
        validator(value)

    @validates('url')
    def validate_url(
        self,
        value,
        **kwargs,
    ):
        validator = validate.URL(relative=False, error='Invalid URL.', schemes={'https'}, require_tld=False)
        validator(value)

    @validates('bearer_token')
    def validate_bearer_token(
        self,
        value,
        **kwargs,
    ):
        validator = validate.Length(min=10, error='Invalid bearer token.')
        validator(value)


class DetailedServiceSchema(BaseSchema):
    statistics = fields.Dict()
    organisation_type = field_for(models.Service, 'organisation_type')

    class Meta:
        model = models.Service
        exclude = (
            'api_keys',
            'templates',
            'users',
            'created_by',
            'jobs',
            'email_branding',
            'service_sms_senders',
            'reply_to_email_addresses',
            'message_limit',
            'email_from',
            'whitelist',
            'permissions',
            'inbound_sms',
        )


class NotificationModelSchema(BaseSchema):
    class Meta:
        model = models.Notification
        load_instance = True
        strict = True
        exclude = (
            '_personalisation',
            'job',
            'service',
            'template',
            'api_key',
        )

    status = fields.String(required=False)


class BaseTemplateSchema(BaseSchema):
    reply_to = fields.Method('get_reply_to', allow_none=True, deserialize='set_reply_to')
    reply_to_text = fields.Method('get_reply_to_text', allow_none=True, deserialize='set_reply_to')
    provider_id = field_for(models.Template, 'provider_id')
    communication_item_id = field_for(models.Template, 'communication_item_id')

    def set_reply_to(self, obj):
        return str(obj)

    def get_reply_to(
        self,
        obj,
    ):
        return obj.reply_to

    def get_reply_to_text(
        self,
        obj,
    ):
        return obj.get_reply_to_text()

    class Meta:
        model = models.Template
        exclude = ('service_id', 'jobs', 'service_letter_contact_id')
        strict = True
        include_relationships = True
        load_instance = True


class TemplateSchema(BaseTemplateSchema):
    created_by = field_for(models.Template, 'created_by', required=True)
    process_type = field_for(models.Template, 'process_type')
    redact_personalisation = fields.Method('redact', allow_none=True, deserialize='set_redact')

    def set_redact(self, obj):
        return bool(obj)

    def redact(
        self,
        template,
    ):
        return template.redact_personalisation

    @validates('communication_item_id')
    def validate_communication_item_id(
        self,
        value,
        **kwargs,
    ):
        if value is not None:
            try:
                get_communication_item(value)
            except NoResultFound:
                raise ValidationError(f'Invalid communication item id: {value}')

    @validates_schema
    def validate_type(
        self,
        data,
        **kwargs,
    ):
        if data.get('template_type') in [EMAIL_TYPE, LETTER_TYPE]:
            subject = data.get('subject')
            if not subject or subject.strip() == '':
                raise ValidationError('Invalid template subject', 'subject')
        provider_id = data.get('provider_id')
        if provider_id is not None and not validate_providers.is_provider_valid(provider_id, data.get('template_type')):
            raise ValidationError(f'Invalid provider id: {provider_id}', 'provider_id')


class TemplateHistorySchema(BaseSchema):
    reply_to = fields.Method('get_reply_to', allow_none=True, deserialize='set_reply_to')
    reply_to_text = fields.Method('get_reply_to_text', allow_none=True, deserialize='set_reply_to')
    provider_id = field_for(models.Template, 'provider_id')

    created_by = fields.Nested(UserSchema, only=['id', 'name', 'email_address'], dump_only=True)
    created_at = field_for(models.Template, 'created_at', format=DATE_FORMAT)

    def get_reply_to(
        self,
        template,
    ):
        return template.reply_to

    def set_reply_to(
        self,
        obj,
    ):
        return str(obj)

    def get_reply_to_text(
        self,
        template,
    ):
        return template.get_reply_to_text()

    class Meta:
        model = models.TemplateHistory
        # include_relationships = True


class ApiKeySchema(BaseSchema):
    created_by = field_for(models.ApiKey, 'created_by', required=True)
    key_type = field_for(models.ApiKey, 'key_type', required=True)

    class Meta:
        model = models.ApiKey
        exclude = ('service', '_secret')
        strict = True
        load_instance = True


class JobSchema(BaseSchema):
    created_by_user = fields.Nested(
        UserSchema, attribute='created_by', dump_to='created_by', only=['id', 'name'], dump_only=True
    )
    created_by = field_for(models.Job, 'created_by', required=True, load_only=True)

    job_status = field_for(models.JobStatus, 'name', required=False)

    scheduled_for = fields.DateTime()
    service_name = fields.Nested(
        ServiceSchema, attribute='service', dump_to='service_name', only=['name'], dump_only=True
    )

    @validates('scheduled_for')
    def validate_scheduled_for(
        self,
        value,
        **kwargs,
    ):
        _validate_datetime_not_in_past(value)
        _validate_datetime_not_more_than_96_hours_in_future(value)

    class Meta:
        model = models.Job
        exclude = ('notifications', 'notifications_sent', 'notifications_delivered', 'notifications_failed')
        strict = True


class NotificationSchema(ma.Schema):
    class Meta:
        strict = True

    status = fields.String(required=False)
    personalisation = fields.Dict(required=False)


class SmsNotificationSchema(NotificationSchema):
    to = fields.Str(required=True)
    sms_sender_id = fields.UUID(required=True)

    @validates('to')
    def validate_to(
        self,
        value,
        **kwargs,
    ):
        try:
            validate_phone_number(value, international=True)
        except InvalidPhoneError as error:
            raise ValidationError('Invalid phone number: {}'.format(error))

    @post_load
    def format_phone_number(
        self,
        item,
        **kwargs,
    ):
        item['to'] = validate_and_format_phone_number(item['to'], international=True)
        return item


class EmailNotificationSchema(NotificationSchema):
    to = fields.Str(required=True)
    template = fields.Str(required=True)

    @validates('to')
    def validate_to(
        self,
        value,
        **kwargs,
    ):
        try:
            validate_email_address(value)
        except InvalidEmailError as e:
            raise ValidationError(str(e))


class SmsTemplateNotificationSchema(SmsNotificationSchema):
    template = fields.Str(required=True)
    job = fields.String()


class JobSmsTemplateNotificationSchema(SmsNotificationSchema):
    template = fields.Str(required=True)
    job = fields.String(required=True)


class JobEmailTemplateNotificationSchema(EmailNotificationSchema):
    template = fields.Str(required=True)
    job = fields.String(required=True)


class SmsAdminNotificationSchema(SmsNotificationSchema):
    content = fields.Str(required=True)


class NotificationWithTemplateSchema(BaseSchema):
    class Meta:
        model = models.Notification
        strict = True

    template = fields.Nested(
        TemplateSchema,
        only=[
            'id',
            'version',
            'name',
            'template_type',
            'content',
            'subject',
            'redact_personalisation',
        ],
        dump_only=True,
    )
    job = fields.Nested(JobSchema, only=['id', 'original_file_name'], dump_only=True)
    created_by = fields.Nested(UserSchema, only=['id', 'name', 'email_address'], dump_only=True)
    status = fields.String(required=False)
    personalisation = fields.Dict(required=False)
    key_type = field_for(models.Notification, 'key_type', required=True)
    key_name = fields.String()

    @pre_dump
    def add_api_key_name(
        self,
        in_data,
        **kwargs,
    ):
        if in_data.api_key:
            in_data.key_name = in_data.api_key.name
        else:
            in_data.key_name = None
        return in_data


class NotificationWithPersonalisationSchema(NotificationWithTemplateSchema):
    template_history = fields.Nested(
        TemplateHistorySchema,
        attribute='template',
        only=['id', 'name', 'template_type', 'content', 'subject', 'version'],
        dump_only=True,
    )

    class Meta(NotificationWithTemplateSchema.Meta):
        # mark as many fields as possible as required since this is a public api.
        # WARNING: Does _not_ reference fields computed in handle_template_merge, such as
        # 'body', 'subject' [for emails], and 'content_char_count'
        fields = (
            'id',
            'to',
            'job_row_number',
            'template_version',
            'billable_units',
            'notification_type',
            'created_at',
            'sent_at',
            'sent_by',
            'updated_at',
            'status',
            'reference',
            'personalisation',
            'service',
            'job',
            'api_key',
            'template_history',
            'sms_sender_id',
        )
        include_relationships = True

    @pre_dump
    def handle_personalisation_property(
        self,
        in_data,
        **kwargs,
    ):
        self.personalisation = in_data.personalisation
        return in_data

    @post_dump
    def handle_template_merge(
        self,
        in_data,
        **kwargs,
    ):
        in_data['template'] = in_data.pop('template_history')
        template = get_template_instance(in_data['template'], in_data['personalisation'])
        in_data['body'] = str(template)
        if in_data['template']['template_type'] != SMS_TYPE:
            in_data['subject'] = template.subject
            in_data['content_char_count'] = None
        else:
            in_data['content_char_count'] = template.content_count

        in_data.pop('personalisation', None)
        in_data['template'].pop('content', None)
        in_data['template'].pop('subject', None)
        return in_data


class InvitedUserSchema(BaseSchema):
    auth_type = field_for(models.InvitedUser, 'auth_type', default=EMAIL_AUTH_TYPE)

    class Meta:
        model = models.InvitedUser
        strict = True
        include_relationships = True

    @validates('email_address')
    def validate_to(
        self,
        value,
        **kwargs,
    ):
        try:
            validate_email_address(value)
        except InvalidEmailError as e:
            raise ValidationError(str(e))


class EmailDataSchema(ma.Schema):
    class Meta:
        strict = True

    email = fields.Str(required=True)

    def __init__(
        self,
        partial_email=False,
    ):
        super().__init__()
        self.partial_email = partial_email

    @validates('email')
    def validate_email(
        self,
        value,
        **kwargs,
    ):
        if self.partial_email:
            return
        try:
            validate_email_address(value)
        except InvalidEmailError as e:
            raise ValidationError(str(e))


class SupportEmailDataSchema(ma.Schema):
    class Meta:
        strict = True

    name = fields.Str(required=True)
    email = fields.Str(required=True)
    message = fields.Str(required=True)
    support_type = fields.Str(required=False)

    def __init__(
        self,
        partial_email=False,
    ):
        super().__init__()
        self.partial_email = partial_email

    @validates('email')
    def validate_email(
        self,
        value,
        **kwargs,
    ):
        if self.partial_email:
            return
        try:
            validate_email_address(value)
        except InvalidEmailError as e:
            raise ValidationError(str(e))


class BrandingRequestDataSchema(ma.Schema):
    class Meta:
        strict = True

    email = fields.Str(required=True)
    serviceID = fields.Str(required=True)
    service_name = fields.Str(required=True)
    filename = fields.Str(required=True)

    def __init__(
        self,
        partial_email=False,
    ):
        super().__init__()
        self.partial_email = partial_email

    @validates('email')
    def validate_email(
        self,
        value,
        **kwargs,
    ):
        if self.partial_email:
            return
        try:
            validate_email_address(value)
        except InvalidEmailError as e:
            raise ValidationError(str(e))


class NotificationsFilterSchema(ma.Schema):
    class Meta:
        strict = True

    template_type = fields.Pluck(BaseTemplateSchema, 'template_type', many=True)
    status = fields.Pluck(NotificationModelSchema, 'status', many=True)
    page = fields.Int(required=False)
    page_size = fields.Int(required=False)
    limit_days = fields.Int(required=False)
    include_jobs = fields.Boolean(required=False)
    include_from_test_key = fields.Boolean(required=False)
    older_than = fields.UUID(required=False)
    format_for_csv = fields.String()
    to = fields.String()
    include_one_off = fields.Boolean(required=False)
    count_pages = fields.Boolean(required=False)

    @pre_load
    def handle_multidict(
        self,
        in_data,
        **kwargs,
    ):
        if isinstance(in_data, dict) and hasattr(in_data, 'getlist'):
            out_data = dict([(k, in_data.get(k)) for k in in_data.keys()])
            if 'template_type' in in_data:
                out_data['template_type'] = in_data.getlist('template_type')
            if 'status' in in_data:
                out_data['status'] = in_data.getlist('status')

        return out_data

    @post_load
    def convert_schema_object_to_field(
        self,
        in_data: dict,
        **kwargs,
    ) -> dict:
        if 'template_type' in in_data:
            in_data['template_type'] = [x.template_type for x in in_data['template_type']]
        if 'status' in in_data:
            in_data['status'] = [x.status for x in in_data['status']]
        return in_data

    @validates('page')
    def validate_page(
        self,
        value,
        **kwargs,
    ):
        _validate_positive_number(value)

    @validates('page_size')
    def validate_page_size(
        self,
        value,
        **kwargs,
    ):
        _validate_positive_number(value)


class ServiceHistorySchema(ma.Schema):
    id = fields.UUID()
    name = fields.String()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()
    active = fields.Boolean()
    message_limit = fields.Integer()
    restricted = fields.Boolean()
    email_from = fields.String()
    created_by_id = fields.UUID()
    version = fields.Integer()


class ApiKeyHistorySchema(ma.Schema):
    id = fields.UUID()
    name = fields.String()
    service_id = fields.UUID()
    expiry_date = fields.DateTime()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()
    created_by_id = fields.UUID()


class EventSchema(BaseSchema):
    class Meta:
        model = models.Event
        strict = True


class DaySchema(ma.Schema):
    class Meta:
        strict = True

    day = fields.Date(required=True)

    @validates('day')
    def validate_day(
        self,
        value,
        **kwargs,
    ):
        _validate_not_in_future(value)


class UnarchivedTemplateSchema(BaseSchema):
    archived = fields.Boolean(required=True)

    @validates_schema
    def validate_archived(
        self,
        data,
        **kwargs,
    ):
        if data['archived']:
            raise ValidationError('Template has been deleted', 'template')


class CommunicationItemSchema(BaseSchema):
    class Meta:
        model = models.CommunicationItem

        dump_only = ['id']
        strict = True


# should not be used on its own for dumping - only for loading
create_user_schema = UserSchema()
user_update_schema_load_json = UserUpdateAttributeSchema(load_json=True, partial=True)
user_update_password_schema_load_json = UserUpdatePasswordSchema(load_json=True, partial=True)
service_schema = ServiceSchema()
detailed_service_schema = DetailedServiceSchema()
template_schema = TemplateSchema()
api_key_schema = ApiKeySchema()
job_schema = JobSchema()
sms_admin_notification_schema = SmsAdminNotificationSchema()
sms_template_notification_schema = SmsTemplateNotificationSchema()
job_sms_template_notification_schema = JobSmsTemplateNotificationSchema()
email_notification_schema = EmailNotificationSchema()
job_email_template_notification_schema = JobEmailTemplateNotificationSchema()
notification_schema = NotificationModelSchema()
notification_with_template_schema = NotificationWithTemplateSchema()
notification_with_personalisation_schema = NotificationWithPersonalisationSchema()
invited_user_schema = InvitedUserSchema()
email_data_request_schema = EmailDataSchema()
support_email_data_schema = SupportEmailDataSchema()
branding_request_data_schema = BrandingRequestDataSchema()
partial_email_data_request_schema = EmailDataSchema(partial_email=True)
notifications_filter_schema = NotificationsFilterSchema()
service_history_schema = ServiceHistorySchema()
api_key_history_schema = ApiKeyHistorySchema()
template_history_schema = TemplateHistorySchema()
event_schema = EventSchema()
provider_details_schema = ProviderDetailsSchema()
provider_details_history_schema = ProviderDetailsHistorySchema()
day_schema = DaySchema()
unarchived_template_schema = UnarchivedTemplateSchema()
service_callback_api_schema = ServiceCallbackSchema()
communication_item_schema = CommunicationItemSchema()
