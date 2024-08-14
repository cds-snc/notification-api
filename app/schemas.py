from datetime import date, datetime, timedelta
from uuid import UUID

from dateutil.parser import parse
from flask import current_app
from flask_marshmallow.fields import fields
from marshmallow import (
    EXCLUDE,
    Schema,
    ValidationError,
    post_dump,
    post_load,
    pre_dump,
    pre_load,
    validates,
    validates_schema,
)
from marshmallow_sqlalchemy import field_for
from notifications_utils.recipients import (
    InvalidEmailError,
    InvalidPhoneError,
    validate_and_format_phone_number,
    validate_email_address,
    validate_phone_number,
)

from app import db, marshmallow, models
from app.dao.permissions_dao import permission_dao
from app.models import ServiceEmailReplyTo, ServicePermission
from app.utils import get_template_instance


def _validate_positive_number(value, msg="Not a positive integer"):
    try:
        page_int = int(value)
    except ValueError:
        raise ValidationError(msg)
    if page_int < 1:
        raise ValidationError(msg)


def _validate_datetime_not_too_far_in_future(dte: datetime):
    max_hours = current_app.config["JOBS_MAX_SCHEDULE_HOURS_AHEAD"]
    max_schedule_time = datetime.utcnow() + timedelta(hours=max_hours)
    if dte.timestamp() > max_schedule_time.timestamp():
        msg = f"Date cannot be more than {max_hours} hours in the future"
        raise ValidationError(msg)


def _validate_not_in_future(dte, msg="Date cannot be in the future"):
    if dte > date.today():
        raise ValidationError(msg)


def _validate_datetime_not_in_past(dte: datetime, msg="Date cannot be in the past"):
    if dte.timestamp() < datetime.utcnow().timestamp():
        raise ValidationError(msg)


class FlexibleDateTime(fields.DateTime):
    """
    Allows input data to not contain tz info.
    Outputs data using the output format that marshmallow version 2 used to use, OLD_MARSHMALLOW_FORMAT
    """

    DEFAULT_FORMAT = "flexible"
    # OLD_MARSHMALLOW_FORMAT = "%Y-%m-%dT%H:%M:%S+00:00"
    OLD_MARSHMALLOW_FORMAT = "%Y-%m-%dT%H:%M:%S.%f+00:00"

    def __init__(self, *args, allow_none=True, **kwargs):
        super().__init__(*args, allow_none=allow_none, **kwargs)
        self.DESERIALIZATION_FUNCS["flexible"] = parse
        self.SERIALIZATION_FUNCS["flexible"] = lambda x: x.strftime(self.OLD_MARSHMALLOW_FORMAT)


class UUIDsAsStringsMixin:
    @post_dump()
    def __post_dump(self, data, **kwargs):
        for key, value in data.items():
            if isinstance(value, UUID):
                data[key] = str(value)
            if isinstance(value, list):
                data[key] = [(str(item) if isinstance(item, UUID) else item) for item in value]
        return data


class BaseSchema(marshmallow.SQLAlchemyAutoSchema):  # type: ignore
    class Meta:
        sqla_session = db.session
        load_instance = True
        include_relationships = True
        unknown = EXCLUDE

    def __init__(self, load_json=False, *args, **kwargs):
        self.load_json = load_json
        super(BaseSchema, self).__init__(*args, **kwargs)

    @post_load
    def make_instance(self, data, **kwargs):
        """Deserialize data to an instance of the model. Update an existing row
        if specified in `self.instance` or loaded by primary key(s) in the data;
        else create a new row.
        :param data: Data to deserialize.
        """
        if self.load_json:
            return data
        return super(BaseSchema, self).make_instance(data)


class TemplateCategorySchema(BaseSchema):
    class Meta(BaseSchema.Meta):
        model = models.TemplateCategory

    @validates("name_en")
    def validate_name_en(self, value):
        if not value:
            raise ValidationError("Invalid name")

    @validates("name_fr")
    def validate_name_fr(self, value):
        if not value:
            raise ValidationError("Invalid name")

    @validates("sms_process_type")
    def validate_sms_process_type(self, value):
        if value not in models.TEMPLATE_PROCESS_TYPE:
            raise ValidationError("Invalid SMS process type")

    @validates("email_process_type")
    def validate_email_process_type(self, value):
        if value not in models.TEMPLATE_PROCESS_TYPE:
            raise ValidationError("Invalid email process type")


class UserSchema(BaseSchema):
    permissions = fields.Method("user_permissions", dump_only=True)
    password_changed_at = field_for(models.User, "password_changed_at", format="%Y-%m-%d %H:%M:%S.%f")
    created_at = field_for(models.User, "created_at", format="%Y-%m-%d %H:%M:%S.%f")
    updated_at = FlexibleDateTime()
    logged_in_at = FlexibleDateTime()
    auth_type = field_for(models.User, "auth_type")
    password = fields.String(required=True, load_only=True)

    def user_permissions(self, usr):
        retval = {}
        for x in permission_dao.get_permissions_by_user_id(usr.id):
            service_id = str(x.service_id)
            if service_id not in retval:
                retval[service_id] = []
            retval[service_id].append(x.permission)
        return retval

    class Meta(BaseSchema.Meta):
        model = models.User
        exclude = (
            "_password",
            "created_at",
            "updated_at",
            "verify_codes",
        )

    @validates("name")
    def validate_name(self, value):
        if not value:
            raise ValidationError("Invalid name")

    @validates("email_address")
    def validate_email_address(self, value):
        try:
            validate_email_address(value)
        except InvalidEmailError as e:
            raise ValidationError(str(e))

    @validates("mobile_number")
    def validate_mobile_number(self, value):
        try:
            if value is not None:
                validate_phone_number(value, international=True)
        except InvalidPhoneError as error:
            raise ValidationError("Invalid phone number: {}".format(error))


class UserUpdateAttributeSchema(BaseSchema):
    auth_type = field_for(models.User, "auth_type")

    class Meta(BaseSchema.Meta):
        model = models.User
        exclude = (
            "_password",
            "created_at",
            "failed_login_count",
            "id",
            "logged_in_at",
            "password_changed_at",
            "platform_admin",
            "state",
            "updated_at",
            "verify_codes",
        )

    @validates("name")
    def validate_name(self, value):
        if not value:
            raise ValidationError("Invalid name")

    @validates("email_address")
    def validate_email_address(self, value):
        try:
            validate_email_address(value)
        except InvalidEmailError as e:
            raise ValidationError(str(e))

    @validates("mobile_number")
    def validate_mobile_number(self, value):
        try:
            if value is not None:
                validate_phone_number(value, international=True)
        except InvalidPhoneError as error:
            raise ValidationError("Invalid phone number: {}".format(error))

    @validates_schema(pass_original=True)
    def check_unknown_fields(self, data, original_data, **kwargs):
        for key in original_data:
            if key not in self.fields:
                raise ValidationError("Unknown field name {}".format(key))


class UserUpdatePasswordSchema(BaseSchema):
    class Meta(BaseSchema.Meta):
        model = models.User
        only = "password"

    @validates_schema(pass_original=True)
    def check_unknown_fields(self, data, original_data, **kwargs):
        for key in original_data:
            if key not in self.fields:
                raise ValidationError("Unknown field name {}".format(key))


class ProviderDetailsSchema(BaseSchema):
    created_by = fields.Nested(UserSchema, only=["id", "name", "email_address"], dump_only=True)
    updated_at = FlexibleDateTime()

    class Meta(BaseSchema.Meta):
        model = models.ProviderDetails
        exclude = ["provider_rates"]


class ProviderDetailsHistorySchema(BaseSchema):
    created_by = fields.Nested(UserSchema, only=["id", "name", "email_address"], dump_only=True)
    updated_at = FlexibleDateTime()

    class Meta(BaseSchema.Meta):
        model = models.ProviderDetailsHistory
        # exclude = ("provider_rates", "provider_stats")


class ServiceSchema(BaseSchema, UUIDsAsStringsMixin):
    created_by = field_for(models.Service, "created_by", required=True)
    organisation_type = field_for(models.Service, "organisation_type")
    letter_logo_filename = fields.Method(dump_only=True, serialize="get_letter_logo_filename")
    permissions = fields.Method("serialize_service_permissions", "deserialize_service_permissions")
    email_branding = field_for(models.Service, "email_branding")
    default_branding_is_french = field_for(models.Service, "default_branding_is_french")
    organisation = field_for(models.Service, "organisation")
    override_flag = False
    letter_contact_block = fields.Method(serialize="get_letter_contact")
    go_live_at = field_for(models.Service, "go_live_at", format="%Y-%m-%d %H:%M:%S.%f")
    organisation_notes = field_for(models.Service, "organisation_notes")
    reply_to_email_addresses = fields.Method("serialize_reply_to_email_addresses", "deserialize_reply_to_email_addresses")

    def serialize_reply_to_email_addresses(self, service):
        return [
            {
                "id": str(reply_to.id),
                "email_address": reply_to.email_address,
                "is_default": reply_to.is_default,
                "archived": reply_to.archived
            }
            for reply_to in service.reply_to_email_addresses
        ]

    def deserialize_reply_to_email_addresses(self, in_data):
        if isinstance(in_data, dict) and "reply_to_email_addresses" in in_data:
            reply_to_email_addresses = []
            for reply_to in in_data["reply_to_email_addresses"]:
                reply_to_email_address = ServiceEmailReplyTo(
                    email_address=reply_to["email_address"],
                    is_default=reply_to["is_default"],
                    archived=reply_to["archived"]
                )
                reply_to_email_addresses.append(reply_to_email_address)
            in_data["reply_to_email_addresses"] = reply_to_email_addresses

    def get_letter_logo_filename(self, service):
        return service.letter_branding and service.letter_branding.filename

    def serialize_service_permissions(self, service):
        return [p.permission for p in service.permissions]

    def deserialize_service_permissions(self, in_data):
        if isinstance(in_data, dict) and "permissions" in in_data:
            str_permissions = in_data["permissions"]
            permissions = []
            for p in str_permissions:
                permission = ServicePermission(service_id=in_data["id"], permission=p)
                permissions.append(permission)

            in_data["permissions"] = permissions

        return in_data

    def get_letter_contact(self, service):
        return service.get_default_letter_contact()

    class Meta(BaseSchema.Meta):
        model = models.Service
        dump_only = ["letter_contact_block"]
        exclude = (
            "complaints",
            "created_at",
            "api_keys",
            "letter_contacts",
            "jobs",
            "service_sms_senders",
            "templates",
            "updated_at",
        )

    @validates("permissions")
    def validate_permissions(self, value):
        permissions = [v.permission for v in value]
        for p in permissions:
            if p not in models.SERVICE_PERMISSION_TYPES:
                raise ValidationError("Invalid Service Permission: '{}'".format(p))

        if len(set(permissions)) != len(permissions):
            duplicates = list(set([x for x in permissions if permissions.count(x) > 1]))
            raise ValidationError("Duplicate Service Permission: {}".format(duplicates))

    @pre_load()
    def format_for_data_model(self, in_data, **kwargs):
        if isinstance(in_data, dict) and "permissions" in in_data:
            str_permissions = in_data["permissions"]
            permissions = []
            for p in str_permissions:
                permission = ServicePermission(service_id=in_data["id"], permission=p)
                permissions.append(permission)

            in_data["permissions"] = permissions
        return in_data


class DetailedServiceSchema(BaseSchema):
    statistics = fields.Dict()
    organisation_type = field_for(models.Service, "organisation_type")
    go_live_at = FlexibleDateTime()
    created_at = FlexibleDateTime()
    updated_at = FlexibleDateTime()

    class Meta(BaseSchema.Meta):
        model = models.Service
        exclude = (
            "all_template_folders",
            "annual_billing",
            "api_keys",
            "created_by",
            "email_branding",
            "email_from",
            "inbound_api",
            "inbound_number",
            "inbound_sms",
            "jobs",
            "message_limit",
            "permissions",
            "reply_to_email_addresses",
            "safelist",
            "service_sms_senders",
            "sms_daily_limit",
            "templates",
            "users",
            "version",
        )


class NotificationModelSchema(BaseSchema):
    class Meta(BaseSchema.Meta):
        model = models.Notification
        exclude = (
            "_personalisation",
            "api_key",
            "job",
            "service",
            "template",
        )

    status = fields.String(required=False)
    created_at = FlexibleDateTime()
    sent_at = FlexibleDateTime()
    updated_at = FlexibleDateTime()


class BaseTemplateSchema(BaseSchema):
    reply_to = fields.Method("get_reply_to", allow_none=True)
    reply_to_text = fields.Method("get_reply_to_text", allow_none=True)
    process_type_column = fields.Method("get_hybrid_process_type")

    def get_hybrid_process_type(self, template):
        return template.process_type_column

    def get_reply_to(self, template):
        return template.reply_to

    def get_reply_to_text(self, template):
        return template.get_reply_to_text()

    class Meta(BaseSchema.Meta):
        model = models.Template
        exclude = ("jobs", "service_id", "service_letter_contact_id")


class TemplateSchema(BaseTemplateSchema):
    created_by = field_for(models.Template, "created_by", required=True)
    is_precompiled_letter = fields.Method("get_is_precompiled_letter")
    process_type = field_for(models.Template, "process_type_column")
    template_category = fields.Nested(TemplateCategorySchema, dump_only=True)
    template_category_id = fields.UUID(required=False, allow_none=True)
    redact_personalisation = fields.Method("redact")
    created_at = FlexibleDateTime()
    updated_at = FlexibleDateTime()

    def get_is_precompiled_letter(self, template):
        return template.is_precompiled_letter

    def redact(self, template):
        return template.redact_personalisation

    @validates_schema
    def validate_type(self, data, **kwargs):
        if data.get("template_type") in [models.EMAIL_TYPE, models.LETTER_TYPE]:
            subject = data.get("subject")
            if not subject or subject.strip() == "":
                raise ValidationError("Invalid template subject", "subject")


class ReducedTemplateSchema(TemplateSchema):
    class Meta(BaseSchema.Meta):
        model = models.Template
        exclude = ["content", "jobs", "service_id", "service_letter_contact_id"]


class TemplateHistorySchema(BaseSchema):
    reply_to = fields.Method("get_reply_to", allow_none=True)
    reply_to_text = fields.Method("get_reply_to_text", allow_none=True)
    process_type = field_for(models.Template, "process_type_column")
    template_category = fields.Nested(TemplateCategorySchema, dump_only=True)
    created_by = fields.Nested(UserSchema, only=["id", "name", "email_address"], dump_only=True)
    created_at = field_for(models.Template, "created_at", format="%Y-%m-%d %H:%M:%S.%f")
    updated_at = FlexibleDateTime()

    def get_reply_to(self, template):
        return template.reply_to

    def get_reply_to_text(self, template):
        return template.get_reply_to_text()

    class Meta(BaseSchema.Meta):
        model = models.TemplateHistory


class ApiKeySchema(BaseSchema):
    created_by = field_for(models.ApiKey, "created_by", required=True)
    key_type = field_for(models.ApiKey, "key_type", required=True)
    expiry_date = FlexibleDateTime()
    created_at = FlexibleDateTime()
    updated_at = FlexibleDateTime()

    class Meta(BaseSchema.Meta):
        model = models.ApiKey
        exclude = ("_secret", "service")


class JobSchema(BaseSchema):
    created_by_user = fields.Nested(
        UserSchema,
        attribute="created_by",
        data_key="created_by",
        only=["id", "name"],
        dump_only=True,
    )
    created_by = field_for(models.Job, "created_by", required=True, load_only=True)
    created_at = FlexibleDateTime()
    updated_at = FlexibleDateTime()
    processing_started = FlexibleDateTime()
    processing_finished = FlexibleDateTime()
    api_key_details = fields.Nested(
        ApiKeySchema,
        attribute="api_key",
        data_key="api_key",
        only=["id", "name", "key_type"],
        dump_only=True,
    )
    api_key = field_for(models.Job, "api_key", required=False, load_only=True)

    job_status = field_for(models.JobStatus, "name", required=False)

    scheduled_for = FlexibleDateTime()
    service_name = fields.Nested(
        ServiceSchema,
        attribute="service",
        data_key="service_name",
        only=["name"],
        dump_only=True,
    )
    sender_id = fields.UUID(required=False, allow_none=True)

    @validates("scheduled_for")
    def validate_scheduled_for(self, value):
        _validate_datetime_not_in_past(value)
        _validate_datetime_not_too_far_in_future(value)

    class Meta(BaseSchema.Meta):
        model = models.Job
        exclude = (
            "notifications",
            "notifications_delivered",
            "notifications_failed",
            "notifications_sent",
        )


class NotificationSchema(Schema):
    class Meta(BaseSchema.Meta):
        unknown = EXCLUDE

    status = fields.String(required=False)
    personalisation = fields.Dict(required=False)


class SmsNotificationSchema(NotificationSchema):
    to = fields.Str(required=True)

    @validates("to")
    def validate_to(self, value):
        try:
            validate_phone_number(value, international=True)
        except InvalidPhoneError as error:
            raise ValidationError("Invalid phone number: {}".format(error))

    @post_load
    def format_phone_number(self, item, **kwargs):
        item["to"] = validate_and_format_phone_number(item["to"], international=True)
        return item


class EmailNotificationSchema(NotificationSchema):
    to = fields.Str(required=True)
    template = fields.Str(required=True)

    @validates("to")
    def validate_to(self, value):
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
    class Meta(BaseSchema.Meta):
        model = models.Notification
        # exclude = ("_personalisation", "scheduled_notification")

    template = fields.Nested(
        TemplateSchema,
        only=[
            "id",
            "version",
            "name",
            "template_type",
            "content",
            "subject",
            "redact_personalisation",
            "is_precompiled_letter",
        ],
        dump_only=True,
    )
    job = fields.Nested(JobSchema, only=["id", "original_file_name"], dump_only=True)
    created_by = fields.Nested(UserSchema, only=["id", "name", "email_address"], dump_only=True)
    status = fields.String(required=False)
    personalisation = fields.Dict(required=False)
    key_type = field_for(models.Notification, "key_type", required=True)
    key_name = fields.String()
    created_at = FlexibleDateTime()
    updated_at = FlexibleDateTime()
    sent_at = FlexibleDateTime()

    @pre_dump
    def add_api_key_name(self, in_data, **kwargs):
        if in_data.api_key:
            in_data.key_name = in_data.api_key.name
        else:
            in_data.key_name = None
        return in_data


class NotificationWithPersonalisationSchema(NotificationWithTemplateSchema):
    template_history = fields.Nested(
        TemplateHistorySchema,
        attribute="template",
        only=["id", "name", "template_type", "content", "subject", "version"],
        dump_only=True,
    )

    class Meta(NotificationWithTemplateSchema.Meta):
        # mark as many fields as possible as required since this is a public api.
        # WARNING: Does _not_ reference fields computed in handle_template_merge, such as
        # 'body', 'subject' [for emails], and 'content_char_count'
        fields = (
            # db rows
            "billable_units",
            "created_at",
            "id",
            "job_row_number",
            "notification_type",
            "reference",
            "sent_at",
            "sent_by",
            "status",
            "template_version",
            "to",
            "updated_at",
            # computed fields
            "personalisation",
            # relationships
            "api_key",
            "job",
            "service",
            "template_history",
        )

    @pre_dump
    def handle_personalisation_property(self, in_data, **kwargs):
        self.personalisation = in_data.personalisation
        return in_data

    @post_dump
    def handle_template_merge(self, in_data, **kwargs):
        in_data["template"] = in_data.pop("template_history")
        template = get_template_instance(in_data["template"], in_data["personalisation"])
        in_data["body"] = str(template)
        if in_data["template"]["template_type"] != models.SMS_TYPE:
            in_data["subject"] = template.subject
            in_data["content_char_count"] = None
        else:
            in_data["content_char_count"] = template.content_count

        in_data.pop("personalisation", None)
        in_data["template"].pop("content", None)
        in_data["template"].pop("subject", None)
        return in_data


class InvitedUserSchema(BaseSchema):
    auth_type = field_for(models.InvitedUser, "auth_type")
    created_at = FlexibleDateTime()

    class Meta(BaseSchema.Meta):
        model = models.InvitedUser

    @validates("email_address")
    def validate_to(self, value):
        try:
            validate_email_address(value)
        except InvalidEmailError as e:
            raise ValidationError(str(e))


class EmailDataSchema(Schema):
    class Meta(BaseSchema.Meta):
        unknown = EXCLUDE

    email = fields.Str(required=True)
    next = fields.Str(required=False)
    admin_base_url = fields.Str(required=False)

    def __init__(self, partial_email=False):
        super().__init__()
        self.partial_email = partial_email

    @validates("email")
    def validate_email(self, value):
        if self.partial_email:
            return
        try:
            validate_email_address(value)
        except InvalidEmailError as e:
            raise ValidationError(str(e))


class SupportEmailDataSchema(Schema):
    class Meta(BaseSchema.Meta):
        unknown = EXCLUDE

    name = fields.Str(required=True)
    email = fields.Str(required=True)
    message = fields.Str(required=True)
    support_type = fields.Str(required=False)

    def __init__(self, partial_email=False):
        super().__init__()
        self.partial_email = partial_email

    @validates("email")
    def validate_email(self, value):
        if self.partial_email:
            return
        try:
            validate_email_address(value)
        except InvalidEmailError as e:
            raise ValidationError(str(e))


class NotificationsFilterSchema(Schema):
    class Meta(BaseSchema.Meta):
        unknown = EXCLUDE

    template_type = fields.Nested(BaseTemplateSchema, only=["template_type"], many=True)
    status = fields.Nested(NotificationModelSchema, only=["status"], many=True)
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
    def handle_multidict(self, in_data, **kwargs):
        if isinstance(in_data, dict) and hasattr(in_data, "getlist"):
            out_data = dict([(k, in_data.get(k)) for k in in_data.keys()])
            if "template_type" in in_data:
                out_data["template_type"] = [{"template_type": x} for x in in_data.getlist("template_type")]
            if "status" in in_data:
                out_data["status"] = [{"status": x} for x in in_data.getlist("status")]

        return out_data

    @post_load
    def convert_schema_object_to_field(self, in_data, **kwargs):
        if "template_type" in in_data:
            in_data["template_type"] = [x.template_type for x in in_data["template_type"]]
        if "status" in in_data:
            in_data["status"] = [x.status for x in in_data["status"]]
        return in_data

    @validates("page")
    def validate_page(self, value):
        _validate_positive_number(value)

    @validates("page_size")
    def validate_page_size(self, value):
        _validate_positive_number(value)


class ServiceHistorySchema(Schema):
    class Meta:
        unknown = EXCLUDE

    id = fields.UUID()
    name = fields.String()
    created_at = FlexibleDateTime()
    updated_at = FlexibleDateTime()
    active = fields.Boolean()
    message_limit = fields.Integer()
    sms_daily_limit = fields.Integer()
    restricted = fields.Boolean()
    email_from = fields.String()
    created_by_id = fields.UUID()
    version = fields.Integer()
    reply_to_email_addresses = fields.List(fields.String())


class ApiKeyHistorySchema(Schema):
    class Meta:
        unknown = EXCLUDE

    id = fields.UUID()
    name = fields.String()
    service_id = fields.UUID()
    expiry_date = FlexibleDateTime()
    created_at = FlexibleDateTime()
    updated_at = FlexibleDateTime()
    created_by_id = fields.UUID()


class EventSchema(BaseSchema):
    created_at = FlexibleDateTime()

    class Meta(BaseSchema.Meta):
        model = models.Event


class DaySchema(Schema):
    class Meta(BaseSchema.Meta):
        unknown = EXCLUDE

    day = fields.Date(required=True)

    @validates("day")
    def validate_day(self, value):
        _validate_not_in_future(value)


class UnarchivedTemplateSchema(BaseSchema):
    archived = fields.Boolean(required=True)

    @validates_schema
    def validate_archived(self, data, **kwargs):
        if data["archived"]:
            raise ValidationError("Template has been deleted", "template")


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
partial_email_data_request_schema = EmailDataSchema(partial_email=True)
notifications_filter_schema = NotificationsFilterSchema()
service_history_schema = ServiceHistorySchema()
api_key_history_schema = ApiKeyHistorySchema()
template_history_schema = TemplateHistorySchema()
template_category_schema = TemplateCategorySchema()
reduced_template_schema = ReducedTemplateSchema()
event_schema = EventSchema()
provider_details_schema = ProviderDetailsSchema()
provider_details_history_schema = ProviderDetailsHistorySchema()
day_schema = DaySchema()
unarchived_template_schema = UnarchivedTemplateSchema()
