import datetime
import itertools
import uuid
from enum import Enum
from typing import Any, Iterable, Literal

from flask import current_app, url_for
from flask_sqlalchemy.model import DefaultMeta
from notifications_utils.columns import Columns
from notifications_utils.letter_timings import get_letter_timings
from notifications_utils.recipients import (
    InvalidEmailError,
    InvalidPhoneError,
    try_validate_and_format_phone_number,
    validate_email_address,
    validate_phone_number,
)
from notifications_utils.template import (
    LetterPrintTemplate,
    PlainTextEmailTemplate,
    SMSMessageTemplate,
)
from notifications_utils.timezones import (
    convert_local_timezone_to_utc,
    convert_utc_to_local_timezone,
)
from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, JSONB, UUID
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.ext.hybrid import hybrid_property

from app import (
    DATETIME_FORMAT,
    db,
    signer_api_key,
    signer_bearer_token,
    signer_inbound_sms,
    signer_personalisation,
)
from app.clients.sms import SmsSendingVehicles
from app.encryption import check_hash, hashpw
from app.history_meta import Versioned

TemplateType = Literal["sms", "email", "letter"]

SMS_TYPE = "sms"
EMAIL_TYPE = "email"
LETTER_TYPE = "letter"

TEMPLATE_TYPES = [SMS_TYPE, EMAIL_TYPE, LETTER_TYPE]

template_types = db.Enum(*TEMPLATE_TYPES, name="template_type")

NORMAL = "normal"
PRIORITY = "priority"
BULK = "bulk"
TEMPLATE_PROCESS_TYPE = [NORMAL, PRIORITY, BULK]


SMS_AUTH_TYPE = "sms_auth"
EMAIL_AUTH_TYPE = "email_auth"
SECURITY_KEY_AUTH_TYPE = "security_key_auth"
USER_AUTH_TYPE = [SMS_AUTH_TYPE, EMAIL_AUTH_TYPE, SECURITY_KEY_AUTH_TYPE]

DELIVERY_STATUS_CALLBACK_TYPE = "delivery_status"
COMPLAINT_CALLBACK_TYPE = "complaint"
SERVICE_CALLBACK_TYPES = [DELIVERY_STATUS_CALLBACK_TYPE, COMPLAINT_CALLBACK_TYPE]
DEFAULT_SMS_ANNUAL_LIMIT = 100000
DEFAULT_EMAIL_ANNUAL_LIMIT = 20000000

NOTIFY_USER_ID = "00000000-0000-0000-0000-000000000000"

sms_sending_vehicles = db.Enum(*[vehicle.value for vehicle in SmsSendingVehicles], name="sms_sending_vehicles")


EMAIL_STATUS_FORMATTED = {
    "failed": "Failed",
    "technical-failure": "Tech issue",
    "temporary-failure": "Content or inbox issue",
    "virus-scan-failed": "Attachment has virus",
    "delivered": "Delivered",
    "sending": "In transit",
    "created": "In transit",
    "sent": "Delivered",
    "pending": "In transit",
    "pending-virus-check": "In transit",
    "pii-check-failed": "Exceeds Protected A",
}

SMS_STATUS_FORMATTED = {
    "failed": "Failed",
    "technical-failure": "Tech issue",
    "temporary-failure": "Carrier issue",
    "permanent-failure": "No such number",
    "delivered": "Delivered",
    "sending": "In transit",
    "created": "In transit",
    "pending": "In transit",
    "sent": "Sent",
}


def filter_null_value_fields(obj):
    return dict(filter(lambda x: x[1] is not None, obj.items()))


class HistoryModel:
    @classmethod
    def from_original(cls, original):
        history = cls()
        history.update_from_original(original)
        return history

    def update_from_original(self, original):
        for c in self.__table__.columns:
            # in some cases, columns may have different names to their underlying db column -  so only copy those
            # that we can, and leave it up to subclasses to deal with any oddities/properties etc.
            if hasattr(original, c.name):
                setattr(self, c.name, getattr(original, c.name))
            else:
                current_app.logger.debug("{} has no column {} to copy from".format(original, c.name))


BaseModel: DefaultMeta = db.Model


class User(BaseModel):
    __tablename__ = "users"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String, nullable=False, index=True, unique=False)
    email_address = db.Column(db.String(255), nullable=False, index=True, unique=True)
    created_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=False,
        default=datetime.datetime.utcnow,
    )
    updated_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=True,
        onupdate=datetime.datetime.utcnow,
    )
    _password = db.Column(db.String, index=False, unique=False, nullable=False)
    mobile_number = db.Column(db.String, index=False, unique=False, nullable=True)
    password_changed_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=False,
        default=datetime.datetime.utcnow,
    )
    logged_in_at = db.Column(db.DateTime, nullable=True)
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    state = db.Column(db.String, nullable=False, default="pending")
    platform_admin = db.Column(db.Boolean, nullable=False, default=False)
    current_session_id = db.Column(UUID(as_uuid=True), nullable=True)
    auth_type = db.Column(
        db.String,
        db.ForeignKey("auth_type.name"),
        index=True,
        nullable=False,
        default=EMAIL_AUTH_TYPE,
    )
    blocked = db.Column(db.Boolean, nullable=False, default=False)
    additional_information = db.Column(JSONB(none_as_null=True), nullable=True, default={})
    password_expired = db.Column(db.Boolean, nullable=False, default=False)
    verified_phonenumber = db.Column(db.Boolean, nullable=True, default=False)

    # either email auth or a mobile number must be provided
    CheckConstraint("auth_type = 'email_auth' or mobile_number is not null")

    services = db.relationship("Service", secondary="user_to_service", backref="users")
    organisations = db.relationship("Organisation", secondary="user_to_organisation", backref="users")

    @property
    def password(self):
        raise AttributeError("Password not readable")

    @password.setter
    def password(self, password):
        self._password = hashpw(password)

    def check_password(self, password):
        if self.blocked:
            return False

        return check_hash(password, self._password)

    def get_permissions(self, service_id=None):
        from app.dao.permissions_dao import permission_dao

        if service_id:
            return [x.permission for x in permission_dao.get_permissions_by_user_id_and_service_id(self.id, service_id)]

        retval = {}
        for x in permission_dao.get_permissions_by_user_id(self.id):
            service_id = str(x.service_id)
            if service_id not in retval:
                retval[service_id] = []
            retval[service_id].append(x.permission)
        return retval

    def serialize(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email_address": self.email_address,
            "auth_type": self.auth_type,
            "current_session_id": self.current_session_id,
            "failed_login_count": self.failed_login_count,
            "logged_in_at": self.logged_in_at.strftime(DATETIME_FORMAT) if self.logged_in_at else None,
            "mobile_number": self.mobile_number,
            "organisations": [x.id for x in self.organisations if x.active],
            "password_changed_at": (
                self.password_changed_at.strftime("%Y-%m-%d %H:%M:%S.%f") if self.password_changed_at else None
            ),
            "permissions": self.get_permissions(),
            "platform_admin": self.platform_admin,
            "services": [x.id for x in self.services if x.active],
            "state": self.state,
            "blocked": self.blocked,
            "additional_information": self.additional_information,
            "password_expired": self.password_expired,
            "verified_phonenumber": self.verified_phonenumber,
        }

    def serialize_for_users_list(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email_address": self.email_address,
            "mobile_number": self.mobile_number,
        }


class ServiceUser(BaseModel):
    __tablename__ = "user_to_service"
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), primary_key=True)
    service_id = db.Column(UUID(as_uuid=True), db.ForeignKey("services.id"), primary_key=True)

    __table_args__ = (UniqueConstraint("user_id", "service_id", name="uix_user_to_service"),)


user_to_organisation = db.Table(
    "user_to_organisation",
    db.Model.metadata,
    db.Column("user_id", UUID(as_uuid=True), db.ForeignKey("users.id")),
    db.Column("organisation_id", UUID(as_uuid=True), db.ForeignKey("organisation.id")),
    UniqueConstraint("user_id", "organisation_id", name="uix_user_to_organisation"),
)


user_folder_permissions = db.Table(
    "user_folder_permissions",
    db.Model.metadata,
    db.Column("user_id", UUID(as_uuid=True), primary_key=True),
    db.Column(
        "template_folder_id",
        UUID(as_uuid=True),
        db.ForeignKey("template_folder.id"),
        primary_key=True,
    ),
    db.Column("service_id", UUID(as_uuid=True), primary_key=True),
    db.ForeignKeyConstraint(
        ["user_id", "service_id"],
        ["user_to_service.user_id", "user_to_service.service_id"],
    ),
    db.ForeignKeyConstraint(
        ["template_folder_id", "service_id"],
        ["template_folder.id", "template_folder.service_id"],
    ),
)


BRANDING_GOVUK = "fip_english"  # Deprecated outside migrations
BRANDING_ORG = "org"  # Used in migrations only - do not remove or they will break
BRANDING_ORG_BANNER = "org_banner"  # Used in migrations only - do not remove or they will break
BRANDING_ORG_NEW = "custom_logo"  # Use this and BRANDING_ORG_BANNER_NEW for actual code
BRANDING_BOTH_EN = "both_english"
BRANDING_BOTH_FR = "both_french"
BRANDING_ORG_BANNER_NEW = "custom_logo_with_background_colour"
BRANDING_NO_BRANDING = "no_branding"
BRANDING_TYPES = [
    BRANDING_ORG_NEW,
    BRANDING_BOTH_EN,
    BRANDING_BOTH_FR,
    BRANDING_ORG_BANNER_NEW,
    BRANDING_NO_BRANDING,
]


class BrandingTypes(BaseModel):
    __tablename__ = "branding_type"
    name = db.Column(db.String(255), primary_key=True)


class EmailBranding(BaseModel):
    __tablename__ = "email_branding"
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    colour = db.Column(db.String(7), nullable=True)
    logo = db.Column(db.String(255), nullable=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    text = db.Column(db.String(255), nullable=True)
    brand_type = db.Column(
        db.String(255),
        db.ForeignKey("branding_type.name"),
        index=True,
        nullable=False,
        default=BRANDING_ORG_NEW,
    )
    organisation_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("organisation.id", ondelete="SET NULL"), index=True, nullable=True
    )
    organisation = db.relationship("Organisation", back_populates="email_branding", foreign_keys=[organisation_id])
    alt_text_en = db.Column(db.String(), nullable=True)
    alt_text_fr = db.Column(db.String(), nullable=True)
    created_by_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), index=True, nullable=False)
    created_by = db.relationship("User", foreign_keys=[created_by_id], lazy="select")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_by_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), index=True, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)
    updated_by = db.relationship("User", foreign_keys=[updated_by_id], lazy="select")

    def serialize(self) -> dict:
        serialized = {
            "id": str(self.id),
            "colour": self.colour,
            "logo": self.logo,
            "name": self.name,
            "text": self.text,
            "brand_type": self.brand_type,
            "organisation_id": str(self.organisation_id) if self.organisation_id else "",
            "alt_text_en": self.alt_text_en,
            "alt_text_fr": self.alt_text_fr,
            "created_by_id": str(self.created_by_id),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "updated_by_id": str(self.updated_by_id),
        }

        return serialized


service_email_branding = db.Table(
    "service_email_branding",
    db.Model.metadata,
    # service_id is a primary key as you can only have one email branding per service
    db.Column(
        "service_id",
        UUID(as_uuid=True),
        db.ForeignKey("services.id"),
        primary_key=True,
        nullable=False,
    ),
    db.Column(
        "email_branding_id",
        UUID(as_uuid=True),
        db.ForeignKey("email_branding.id"),
        nullable=False,
    ),
)


class LetterBranding(BaseModel):
    __tablename__ = "letter_branding"
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(255), unique=True, nullable=False)
    filename = db.Column(db.String(255), unique=True, nullable=False)

    def serialize(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "filename": self.filename,
        }


service_letter_branding = db.Table(
    "service_letter_branding",
    db.Model.metadata,
    # service_id is a primary key as you can only have one letter branding per service
    db.Column(
        "service_id",
        UUID(as_uuid=True),
        db.ForeignKey("services.id"),
        primary_key=True,
        nullable=False,
    ),
    db.Column(
        "letter_branding_id",
        UUID(as_uuid=True),
        db.ForeignKey("letter_branding.id"),
        nullable=False,
    ),
)


INTERNATIONAL_SMS_TYPE = "international_sms"
INBOUND_SMS_TYPE = "inbound_sms"
SCHEDULE_NOTIFICATIONS = "schedule_notifications"
EMAIL_AUTH = "email_auth"
LETTERS_AS_PDF = "letters_as_pdf"
PRECOMPILED_LETTER = "precompiled_letter"
UPLOAD_DOCUMENT = "upload_document"
EDIT_FOLDER_PERMISSIONS = "edit_folder_permissions"
UPLOAD_LETTERS = "upload_letters"

SERVICE_PERMISSION_TYPES = [
    EMAIL_TYPE,
    SMS_TYPE,
    LETTER_TYPE,
    INTERNATIONAL_SMS_TYPE,
    INBOUND_SMS_TYPE,
    SCHEDULE_NOTIFICATIONS,
    EMAIL_AUTH,
    LETTERS_AS_PDF,
    UPLOAD_DOCUMENT,
    EDIT_FOLDER_PERMISSIONS,
    UPLOAD_LETTERS,
]


class ServicePermissionTypes(BaseModel):
    __tablename__ = "service_permission_types"

    name = db.Column(db.String(255), primary_key=True)


class Domain(BaseModel):
    __tablename__ = "domain"
    domain = db.Column(db.String(255), primary_key=True)
    organisation_id = db.Column(
        "organisation_id",
        UUID(as_uuid=True),
        db.ForeignKey("organisation.id"),
        nullable=False,
    )


ORGANISATION_TYPES = [
    "central",
    "province_or_territory",
    "local",
    "nhs_central",
    "nhs_local",
    "nhs_gp",
    "emergency_service",
    "school_or_college",
    "other",
]

CROWN_ORGANISATION_TYPES = ["nhs_central"]
NON_CROWN_ORGANISATION_TYPES = [
    "local",
    "nhs_local",
    "nhs_gp",
    "emergency_service",
    "school_or_college",
]
NHS_ORGANISATION_TYPES = ["nhs_central", "nhs_local", "nhs_gp"]


class OrganisationTypes(BaseModel):
    __tablename__ = "organisation_types"

    name = db.Column(db.String(255), primary_key=True)
    is_crown = db.Column(db.Boolean, nullable=True)
    annual_free_sms_fragment_limit = db.Column(db.BigInteger, nullable=False)


class Organisation(BaseModel):
    __tablename__ = "organisation"
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=False)
    name = db.Column(db.String(255), nullable=False, unique=True, index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)
    agreement_signed = db.Column(db.Boolean, nullable=True)
    agreement_signed_at = db.Column(db.DateTime, nullable=True)
    agreement_signed_by_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("users.id"),
        nullable=True,
    )
    agreement_signed_by = db.relationship("User")
    agreement_signed_on_behalf_of_name = db.Column(db.String(255), nullable=True)
    agreement_signed_on_behalf_of_email_address = db.Column(db.String(255), nullable=True)
    agreement_signed_version = db.Column(db.Float, nullable=True)
    crown = db.Column(db.Boolean, nullable=True)
    default_branding_is_french = db.Column(db.Boolean, index=False, unique=False, nullable=False, default=False)
    organisation_type = db.Column(
        db.String(255),
        db.ForeignKey("organisation_types.name"),
        unique=False,
        nullable=True,
    )
    request_to_go_live_notes = db.Column(db.Text)

    domains = db.relationship(
        "Domain",
    )

    email_branding = db.relationship("EmailBranding", uselist=False)
    email_branding_id = db.Column(
        UUID(as_uuid=True),
        nullable=True,
    )

    letter_branding = db.relationship("LetterBranding")
    letter_branding_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("letter_branding.id"),
        nullable=True,
    )

    @property
    def live_services(self):
        return [service for service in self.services if service.active and not service.restricted]

    @property
    def domain_list(self):
        return [domain.domain for domain in self.domains]

    def serialize(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "active": self.active,
            "crown": self.crown,
            "default_branding_is_french": self.default_branding_is_french,
            "organisation_type": self.organisation_type,
            "letter_branding_id": self.letter_branding_id,
            "email_branding_id": self.email_branding_id,
            "agreement_signed": self.agreement_signed,
            "agreement_signed_at": self.agreement_signed_at,
            "agreement_signed_by_id": self.agreement_signed_by_id,
            "agreement_signed_on_behalf_of_name": self.agreement_signed_on_behalf_of_name,
            "agreement_signed_on_behalf_of_email_address": self.agreement_signed_on_behalf_of_email_address,
            "agreement_signed_version": self.agreement_signed_version,
            "domains": self.domain_list,
            "request_to_go_live_notes": self.request_to_go_live_notes,
            "count_of_live_services": len(self.live_services),
        }

    def serialize_for_list(self) -> dict:
        return {
            "name": self.name,
            "id": str(self.id),
            "active": self.active,
            "count_of_live_services": len(self.live_services),
            "domains": self.domain_list,
            "organisation_type": self.organisation_type,
        }


class Service(BaseModel, Versioned):
    __tablename__ = "services"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(255), nullable=False, unique=True)
    created_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=False,
        default=datetime.datetime.utcnow,
    )
    updated_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=True,
        onupdate=datetime.datetime.utcnow,
    )
    active = db.Column(db.Boolean, index=False, unique=False, nullable=False, default=True)
    message_limit = db.Column(db.BigInteger, index=False, unique=False, nullable=False)
    sms_daily_limit = db.Column(db.BigInteger, index=False, unique=False, nullable=False)
    restricted = db.Column(db.Boolean, index=False, unique=False, nullable=False)
    research_mode = db.Column(db.Boolean, index=False, unique=False, nullable=False, default=False)
    email_from = db.Column(db.Text, index=False, unique=True, nullable=False)
    created_by_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), index=True, nullable=False)
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    default_branding_is_french = db.Column(db.Boolean, index=False, unique=False, nullable=False, default=False)
    prefix_sms = db.Column(db.Boolean, nullable=False, default=True)
    organisation_type = db.Column(
        db.String(255),
        db.ForeignKey("organisation_types.name"),
        unique=False,
        nullable=True,
    )
    crown = db.Column(db.Boolean, index=False, nullable=True)
    rate_limit = db.Column(db.Integer, index=False, nullable=False, default=1000)
    contact_link = db.Column(db.String(255), nullable=True, unique=False)
    volume_sms = db.Column(db.Integer(), nullable=True, unique=False)
    volume_email = db.Column(db.Integer(), nullable=True, unique=False)
    volume_letter = db.Column(db.Integer(), nullable=True, unique=False)
    consent_to_research = db.Column(db.Boolean, nullable=True)
    count_as_live = db.Column(db.Boolean, nullable=False, default=True)
    go_live_user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=True)
    go_live_user = db.relationship("User", foreign_keys=[go_live_user_id])
    go_live_at = db.Column(db.DateTime, nullable=True)
    sending_domain = db.Column(db.String(255), nullable=True, unique=False)
    organisation_notes = db.Column(db.String(255), nullable=True, unique=False)
    sensitive_service = db.Column(db.Boolean, nullable=True)
    organisation_id = db.Column(UUID(as_uuid=True), db.ForeignKey("organisation.id"), index=True, nullable=True)
    organisation = db.relationship("Organisation", backref="services")
    email_annual_limit = db.Column(db.BigInteger, nullable=False, default=DEFAULT_EMAIL_ANNUAL_LIMIT)
    sms_annual_limit = db.Column(db.BigInteger, nullable=False, default=DEFAULT_SMS_ANNUAL_LIMIT)

    email_branding = db.relationship(
        "EmailBranding",
        secondary=service_email_branding,
        uselist=False,
        backref=db.backref("services", lazy="dynamic"),
    )
    letter_branding = db.relationship(
        "LetterBranding",
        secondary=service_letter_branding,
        uselist=False,
        backref=db.backref("services", lazy="dynamic"),
    )

    @classmethod
    def from_json(cls, data):
        """
        Assumption: data has been validated appropriately.

        Returns a Service object based on the provided data. Deserialises created_by to created_by_id as marshmallow
        would.
        """
        # validate json with marshmallow
        fields = data.copy()

        fields["created_by_id"] = fields.pop("created_by", None)
        fields["organisation_id"] = fields.pop("organisation", None)
        fields["go_live_user_id"] = fields.pop("go_live_user", None)
        fields.pop("safelist", None)
        fields.pop("permissions", None)
        fields.pop("service_callback_api", None)
        fields.pop("service_data_retention", None)
        fields.pop("all_template_folders", None)
        fields.pop("users", None)
        fields.pop("annual_billing", None)
        fields.pop("inbound_api", None)
        fields.pop("inbound_number", None)
        fields.pop("inbound_sms", None)
        fields.pop("email_branding", None)
        fields.pop("letter_logo_filename", None)
        fields.pop("letter_contact_block", None)
        fields.pop("email_branding", None)
        fields["sms_daily_limit"] = fields.get("sms_daily_limit", 100)
        fields["email_annual_limit"] = fields.get("email_annual_limit", DEFAULT_EMAIL_ANNUAL_LIMIT)
        fields["sms_annual_limit"] = fields.get("sms_annual_limit", DEFAULT_SMS_ANNUAL_LIMIT)

        return cls(**fields)

    def get_inbound_number(self):
        if self.inbound_number and self.inbound_number.active:
            return self.inbound_number.number

    def get_default_sms_sender(self):
        default_sms_sender = [x for x in self.service_sms_senders if x.is_default]
        return default_sms_sender[0].sms_sender if default_sms_sender else None

    def get_default_reply_to_email_address(self):
        default_reply_to = [x for x in self.reply_to_email_addresses if x.is_default]
        return default_reply_to[0].email_address if default_reply_to else None

    def get_default_letter_contact(self):
        default_letter_contact = [x for x in self.letter_contacts if x.is_default]
        return default_letter_contact[0].contact_block if default_letter_contact else None

    def has_permission(self, permission):
        return permission in [p.permission for p in self.permissions]

    def serialize_for_org_dashboard(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "active": self.active,
            "restricted": self.restricted,
            "research_mode": self.research_mode,
        }

    def get_users_with_permission(self, permission):
        from app.dao.permissions_dao import permission_dao

        if permission:
            return permission_dao.get_team_members_with_permission(self.id, permission)
        return []


class AnnualBilling(BaseModel):
    __tablename__ = "annual_billing"
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=False)
    service_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("services.id"),
        unique=False,
        index=True,
        nullable=False,
    )
    financial_year_start = db.Column(db.Integer, nullable=False, default=True, unique=False)
    free_sms_fragment_limit = db.Column(db.Integer, nullable=False, index=False, unique=False)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    UniqueConstraint("financial_year_start", "service_id", name="ix_annual_billing_service_id")
    service = db.relationship(Service, backref=db.backref("annual_billing", uselist=True))

    def serialize_free_sms_items(self) -> dict:
        return {
            "free_sms_fragment_limit": self.free_sms_fragment_limit,
            "financial_year_start": self.financial_year_start,
        }

    def serialize(self) -> dict:
        def serialize_service() -> dict:
            return {"id": str(self.service_id), "name": self.service.name}

        return {
            "id": str(self.id),
            "free_sms_fragment_limit": self.free_sms_fragment_limit,
            "service_id": self.service_id,
            "financial_year_start": self.financial_year_start,
            "created_at": self.created_at.strftime(DATETIME_FORMAT),
            "updated_at": self.updated_at.strftime(DATETIME_FORMAT) if self.updated_at else None,
            "service": serialize_service() if self.service else None,
        }


class InboundNumber(BaseModel):
    __tablename__ = "inbound_numbers"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    number = db.Column(db.String(11), unique=True, nullable=False)
    provider = db.Column(db.String(), nullable=False)
    service_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("services.id"),
        unique=True,
        index=True,
        nullable=True,
    )
    service = db.relationship(Service, backref=db.backref("inbound_number", uselist=False))
    active = db.Column(db.Boolean, index=False, unique=False, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)

    def serialize(self) -> dict:
        def serialize_service() -> dict:
            return {"id": str(self.service_id), "name": self.service.name}

        return {
            "id": str(self.id),
            "number": self.number,
            "provider": self.provider,
            "service": serialize_service() if self.service else None,
            "active": self.active,
            "created_at": self.created_at.strftime(DATETIME_FORMAT),
            "updated_at": self.updated_at.strftime(DATETIME_FORMAT) if self.updated_at else None,
        }


class ServiceSmsSender(BaseModel):
    __tablename__ = "service_sms_senders"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sms_sender = db.Column(db.String(11), nullable=False)
    service_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("services.id"),
        index=True,
        nullable=False,
        unique=False,
    )
    service = db.relationship(Service, backref=db.backref("service_sms_senders", uselist=True))
    is_default = db.Column(db.Boolean, nullable=False, default=True)
    archived = db.Column(db.Boolean, nullable=False, default=False)
    inbound_number_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("inbound_numbers.id"),
        unique=True,
        index=True,
        nullable=True,
    )
    inbound_number = db.relationship(InboundNumber, backref=db.backref("inbound_number", uselist=False))
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)

    def get_reply_to_text(self):
        return try_validate_and_format_phone_number(self.sms_sender)

    def serialize(self) -> dict:
        return {
            "id": str(self.id),
            "sms_sender": self.sms_sender,
            "service_id": str(self.service_id),
            "is_default": self.is_default,
            "archived": self.archived,
            "inbound_number_id": str(self.inbound_number_id) if self.inbound_number_id else None,
            "created_at": self.created_at.strftime(DATETIME_FORMAT),
            "updated_at": self.updated_at.strftime(DATETIME_FORMAT) if self.updated_at else None,
        }


class ServicePermission(BaseModel):
    __tablename__ = "service_permissions"

    service_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("services.id"),
        primary_key=True,
        index=True,
        nullable=False,
    )
    permission = db.Column(
        db.String(255),
        db.ForeignKey("service_permission_types.name"),
        index=True,
        primary_key=True,
        nullable=False,
    )
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)

    service_permission_types = db.relationship(Service, backref=db.backref("permissions", cascade="all, delete-orphan"))

    def __repr__(self):
        return "<{} has service permission: {}>".format(self.service_id, self.permission)


MOBILE_TYPE = "mobile"
EMAIL_TYPE = "email"

SAFELIST_RECIPIENT_TYPE = [MOBILE_TYPE, EMAIL_TYPE]
safelist_recipient_types = db.Enum(*SAFELIST_RECIPIENT_TYPE, name="recipient_type")


class ServiceSafelist(BaseModel):
    __tablename__ = "service_safelist"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_id = db.Column(UUID(as_uuid=True), db.ForeignKey("services.id"), index=True, nullable=False)
    service = db.relationship("Service", backref="safelist")
    recipient_type = db.Column(safelist_recipient_types, nullable=False)
    recipient = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    @classmethod
    def from_string(cls, service_id, recipient_type, recipient):
        instance = cls(service_id=service_id, recipient_type=recipient_type)

        try:
            if recipient_type == MOBILE_TYPE:
                validate_phone_number(recipient, international=True)
                instance.recipient = recipient
            elif recipient_type == EMAIL_TYPE:
                validate_email_address(recipient)
                instance.recipient = recipient
            else:
                raise ValueError("Invalid recipient type")
        except InvalidPhoneError:
            raise ValueError('Invalid safelist: "{}"'.format(recipient))
        except InvalidEmailError:
            raise ValueError('Invalid safelist: "{}"'.format(recipient))
        else:
            return instance

    def __repr__(self):
        return "Recipient {} of type: {}".format(self.recipient, self.recipient_type)


class ServiceInboundApi(BaseModel, Versioned):
    __tablename__ = "service_inbound_api"
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("services.id"),
        index=True,
        nullable=False,
        unique=True,
    )
    service = db.relationship("Service", backref="inbound_api")
    url = db.Column(db.String(), nullable=False)
    _bearer_token = db.Column("bearer_token", db.String(), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=True)
    updated_by = db.relationship("User")
    updated_by_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), index=True, nullable=False)

    @property
    def bearer_token(self):
        if self._bearer_token:
            return signer_bearer_token.verify(self._bearer_token)
        return None

    @bearer_token.setter
    def bearer_token(self, bearer_token):
        if bearer_token:
            self._bearer_token = signer_bearer_token.sign(str(bearer_token))

    def serialize(self) -> dict:
        return {
            "id": str(self.id),
            "service_id": str(self.service_id),
            "url": self.url,
            "updated_by_id": str(self.updated_by_id),
            "created_at": self.created_at.strftime(DATETIME_FORMAT),
            "updated_at": self.updated_at.strftime(DATETIME_FORMAT) if self.updated_at else None,
        }


class ServiceCallbackApi(BaseModel, Versioned):
    __tablename__ = "service_callback_api"
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_id = db.Column(UUID(as_uuid=True), db.ForeignKey("services.id"), index=True, nullable=False)
    service = db.relationship("Service", backref="service_callback_api")
    url = db.Column(db.String(), nullable=False)
    callback_type = db.Column(db.String(), db.ForeignKey("service_callback_type.name"), nullable=True)
    _bearer_token = db.Column("bearer_token", db.String(), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=True)
    updated_by = db.relationship("User")
    updated_by_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), index=True, nullable=False)
    is_suspended = db.Column(db.Boolean, nullable=True, default=False)
    # If is_suspended is False and suspended_at is not None, then the callback was suspended and then unsuspended
    suspended_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("service_id", "callback_type", name="uix_service_callback_type"),)

    @property
    def bearer_token(self):
        if self._bearer_token:
            return signer_bearer_token.verify(self._bearer_token)
        return None

    @bearer_token.setter
    def bearer_token(self, bearer_token):
        if bearer_token:
            self._bearer_token = signer_bearer_token.sign(str(bearer_token))

    def serialize(self) -> dict:
        return {
            "id": str(self.id),
            "service_id": str(self.service_id),
            "url": self.url,
            "updated_by_id": str(self.updated_by_id),
            "created_at": self.created_at.strftime(DATETIME_FORMAT),
            "updated_at": self.updated_at.strftime(DATETIME_FORMAT) if self.updated_at else None,
            "is_suspended": self.is_suspended,
            "suspended_at": self.suspended_at.strftime(DATETIME_FORMAT) if self.suspended_at else None,
        }


class ServiceCallbackType(BaseModel):
    __tablename__ = "service_callback_type"

    name = db.Column(db.String, primary_key=True)


class ApiKey(BaseModel, Versioned):
    __tablename__ = "api_keys"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(255), nullable=False)
    _secret = db.Column("secret", db.String(255), unique=True, nullable=False)
    service_id = db.Column(UUID(as_uuid=True), db.ForeignKey("services.id"), index=True, nullable=False)
    service = db.relationship("Service", backref="api_keys")
    key_type = db.Column(db.String(255), db.ForeignKey("key_types.name"), index=True, nullable=False)
    expiry_date = db.Column(db.DateTime)
    created_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=False,
        default=datetime.datetime.utcnow,
    )
    updated_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=True,
        onupdate=datetime.datetime.utcnow,
    )
    created_by = db.relationship("User")
    created_by_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), index=True, nullable=False)
    compromised_key_info = db.Column(JSONB(none_as_null=True), nullable=True, default={})
    last_used_timestamp = db.Column(db.DateTime, index=False, unique=False, nullable=True, default=None)

    __table_args__ = (
        Index(
            "uix_service_to_key_name",
            "service_id",
            "name",
            unique=True,
            postgresql_where=expiry_date.is_(None),
        ),
    )

    @property
    def secret(self):
        if self._secret:
            return signer_api_key.verify(self._secret)
        return None

    @secret.setter
    def secret(self, secret):
        if secret:
            self._secret = signer_api_key.sign(str(secret))


ApiKeyType = Literal["normal", "team", "test"]
KEY_TYPE_NORMAL: Literal["normal"] = "normal"
KEY_TYPE_TEAM: Literal["team"] = "team"
KEY_TYPE_TEST: Literal["test"] = "test"


class KeyTypes(BaseModel):
    __tablename__ = "key_types"

    name = db.Column(db.String(255), primary_key=True)


class TemplateProcessTypes(BaseModel):
    __tablename__ = "template_process_type"
    name = db.Column(db.String(255), primary_key=True)


class TemplateFolder(BaseModel):
    __tablename__ = "template_folder"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_id = db.Column(UUID(as_uuid=True), db.ForeignKey("services.id"), nullable=False)
    name = db.Column(db.String, nullable=False)
    parent_id = db.Column(UUID(as_uuid=True), db.ForeignKey("template_folder.id"), nullable=True)

    service = db.relationship("Service", backref="all_template_folders")
    parent = db.relationship("TemplateFolder", remote_side=[id], backref="subfolders")
    users = db.relationship(
        "ServiceUser",
        uselist=True,
        backref=db.backref("folders", foreign_keys="user_folder_permissions.c.template_folder_id"),
        secondary="user_folder_permissions",
        primaryjoin="TemplateFolder.id == user_folder_permissions.c.template_folder_id",
    )

    __table_args__: Iterable[Any] = (UniqueConstraint("id", "service_id", name="ix_id_service_id"), {})

    def serialize(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "service_id": self.service_id,
            "users_with_permission": self.get_users_with_permission(),
        }

    def is_parent_of(self, other):
        while other.parent is not None:
            if other.parent == self:
                return True
            other = other.parent
        return False

    def get_users_with_permission(self):
        service_users = self.users
        users_with_permission = [str(service_user.user_id) for service_user in service_users]

        return users_with_permission


template_folder_map = db.Table(
    "template_folder_map",
    db.Model.metadata,
    # template_id is a primary key as a template can only belong in one folder
    db.Column(
        "template_id",
        UUID(as_uuid=True),
        db.ForeignKey("templates.id"),
        primary_key=True,
        nullable=False,
    ),
    db.Column(
        "template_folder_id",
        UUID(as_uuid=True),
        db.ForeignKey("template_folder.id"),
        nullable=False,
    ),
)


PRECOMPILED_TEMPLATE_NAME = "Pre-compiled PDF"


class TemplateCategory(BaseModel):
    __tablename__ = "template_categories"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name_en = db.Column(db.String(255), unique=True, nullable=False)
    name_fr = db.Column(db.String(255), unique=True, nullable=False)
    description_en = db.Column(db.String(200), nullable=True)
    description_fr = db.Column(db.String(200), nullable=True)
    sms_process_type = db.Column(db.String(200), nullable=False)
    email_process_type = db.Column(db.String(200), nullable=False)
    hidden = db.Column(db.Boolean, nullable=False, default=False)
    created_by_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), index=True, nullable=False)
    created_by = db.relationship("User", foreign_keys=[created_by_id], lazy="select")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_by_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), index=True, nullable=True)
    updated_by = db.relationship("User", foreign_keys=[updated_by_id], lazy="select")
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)
    sms_sending_vehicle = db.Column(sms_sending_vehicles, nullable=False, default="long_code")

    def serialize(self):
        return {
            "id": self.id,
            "name_en": self.name_en,
            "name_fr": self.name_fr,
            "description_en": self.description_en,
            "description_fr": self.description_fr,
            "sms_process_type": self.sms_process_type,
            "email_process_type": self.email_process_type,
            "hidden": self.hidden,
            "created_by_id": str(self.created_by_id),
            "created_at": self.created_at,
            "updated_by_id": str(self.updated_by_id),
            "updated_at": self.updated_at,
            "sms_sending_vehicle": self.sms_sending_vehicle,
        }

    @classmethod
    def from_json(cls, data):
        fields = data.copy()
        return cls(**fields)


class TemplateBase(BaseModel):
    __abstract__ = True

    def __init__(self, **kwargs):
        if "template_type" in kwargs:
            self.template_type = kwargs.pop("template_type")

        super().__init__(**kwargs)

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(255), nullable=False)
    template_type: TemplateType = db.Column(template_types, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.datetime.utcnow)
    content = db.Column(db.Text, nullable=False)
    archived = db.Column(db.Boolean, nullable=False, default=False)
    hidden = db.Column(db.Boolean, nullable=False, default=False)
    subject = db.Column(db.Text)
    postage = db.Column(db.String, nullable=True)
    text_direction_rtl = db.Column(db.Boolean, nullable=False, default=False)
    CheckConstraint(
        """
        CASE WHEN template_type = 'letter' THEN
            postage is not null and postage in ('first', 'second')
        ELSE
            postage is null
        END
    """
    )

    @classmethod
    def from_json(cls, data):
        fields = data.copy()
        fields["created_by_id"] = fields.pop("created_by", None)
        fields.pop("redact_personalisation", None)
        fields.pop("reply_to_text", None)
        return cls(**fields)

    @declared_attr
    def service_id(cls):
        return db.Column(UUID(as_uuid=True), db.ForeignKey("services.id"), index=True, nullable=False)

    @declared_attr
    def created_by_id(cls):
        return db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), index=True, nullable=False)

    @declared_attr
    def template_category_id(cls):
        return db.Column(UUID(as_uuid=True), db.ForeignKey("template_categories.id"), index=True, nullable=True)

    @declared_attr
    def template_category(cls):
        return db.relationship("TemplateCategory", primaryjoin="Template.template_category_id == TemplateCategory.id")

    @declared_attr
    def created_by(cls):
        return db.relationship("User")

    @declared_attr
    def process_type_column(cls):
        return db.Column(
            db.String(255),
            db.ForeignKey("template_process_type.name"),
            name="process_type",
            index=True,
            nullable=True,
        )

    @hybrid_property
    def process_type(self):
        if self.template_type == SMS_TYPE:
            return self.process_type_column if self.process_type_column else self.template_category.sms_process_type
        elif self.template_type == EMAIL_TYPE:
            return self.process_type_column if self.process_type_column else self.template_category.email_process_type

    @process_type.setter  # type: ignore
    def process_type(self, value):
        self.process_type_column = value

    @process_type.expression
    def _process_type(self):
        return db.case(
            [
                (self.template_type == "sms", db.coalesce(self.process_type_column, self.template_category.sms_process_type)),
                (self.template_type == "email", db.coalesce(self.process_type_column, self.template_category.email_process_type)),
            ],
            else_=self.process_type_column,
        )

    redact_personalisation = association_proxy("template_redacted", "redact_personalisation")

    @declared_attr
    def service_letter_contact_id(cls):
        return db.Column(
            UUID(as_uuid=True),
            db.ForeignKey("service_letter_contacts.id"),
            nullable=True,
        )

    @declared_attr
    def service_letter_contact(cls):
        return db.relationship("ServiceLetterContact", viewonly=True)

    @property
    def reply_to(self):
        if self.template_type == LETTER_TYPE:
            return self.service_letter_contact_id
        else:
            return None

    @reply_to.setter
    def reply_to(self, value):
        if self.template_type == LETTER_TYPE:
            self.service_letter_contact_id = value
        elif value is None:
            pass
        else:
            raise ValueError("Unable to set sender for {} template".format(self.template_type))

    def get_reply_to_text(self):
        if self.template_type == LETTER_TYPE:
            return self.service_letter_contact.contact_block if self.service_letter_contact else None
        elif self.template_type == EMAIL_TYPE:
            return self.service.get_default_reply_to_email_address()
        elif self.template_type == SMS_TYPE:
            return try_validate_and_format_phone_number(self.service.get_default_sms_sender())
        else:
            return None

    @hybrid_property
    def is_precompiled_letter(self):
        return self.hidden and self.name == PRECOMPILED_TEMPLATE_NAME and self.template_type == LETTER_TYPE

    @is_precompiled_letter.setter  # type: ignore
    def is_precompiled_letter(self, value):
        pass

    def _as_utils_template(self):
        if self.template_type == EMAIL_TYPE:
            return PlainTextEmailTemplate({"content": self.content, "subject": self.subject})
        if self.template_type == SMS_TYPE:
            return SMSMessageTemplate({"content": self.content})
        if self.template_type == LETTER_TYPE:
            return LetterPrintTemplate(
                {"content": self.content, "subject": self.subject},
                contact_block=self.service.get_default_letter_contact(),
            )

    def serialize(self) -> dict:
        serialized = {
            "id": str(self.id),
            "type": self.template_type,
            "created_at": self.created_at.strftime(DATETIME_FORMAT),
            "updated_at": self.updated_at.strftime(DATETIME_FORMAT) if self.updated_at else None,
            "created_by": self.created_by.email_address,
            "version": self.version,
            "body": self.content,
            "subject": self.subject if self.template_type != SMS_TYPE else None,
            "name": self.name,
            "personalisation": {
                key: {
                    "required": True,
                }
                for key in self._as_utils_template().placeholders
            },
            "postage": self.postage,
        }

        return serialized


class Template(TemplateBase):
    __tablename__ = "templates"

    service = db.relationship("Service", backref="templates")
    version = db.Column(db.Integer, default=0, nullable=False)

    folder = db.relationship(
        "TemplateFolder",
        secondary=template_folder_map,
        uselist=False,
        # eagerly load the folder whenever the template object is fetched
        lazy="joined",
        backref=db.backref("templates"),
    )

    def get_link(self):
        # TODO: use "/v2/" route once available
        return url_for(
            "template.get_template_by_id_and_service_id",
            service_id=self.service_id,
            template_id=self.id,
            _external=True,
        )

    @classmethod
    def from_json(cls, data, folder=None):
        """
        Assumption: data has been validated appropriately.
        Returns a Template object based on the provided data.
        """
        fields = data.copy()

        if fields.get("service"):
            fields["service_id"] = fields.pop("service")

        fields.pop("template_redacted", None)

        if folder:
            fields["folder"] = folder
        else:
            fields.pop("folder", None)

        return super(Template, cls).from_json(fields)


class TemplateRedacted(BaseModel):
    __tablename__ = "template_redacted"

    template_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("templates.id"),
        primary_key=True,
        nullable=False,
    )
    redact_personalisation = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_by_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False, index=True)
    updated_by = db.relationship("User")

    # uselist=False as this is a one-to-one relationship
    template = db.relationship(
        "Template",
        uselist=False,
        backref=db.backref("template_redacted", uselist=False),
    )


class TemplateHistory(TemplateBase):
    __tablename__ = "templates_history"

    service = db.relationship("Service")
    version = db.Column(db.Integer, primary_key=True, nullable=False)

    @classmethod
    def from_json(cls, data):
        fields = data.copy()

        if fields.get("service"):
            fields["service_id"] = fields.pop("service")

        fields.pop("template_redacted", None)
        fields.pop("folder", None)
        return super(TemplateHistory, cls).from_json(fields)

    @declared_attr
    def template_category(cls):
        return db.relationship("TemplateCategory", primaryjoin="TemplateHistory.template_category_id == TemplateCategory.id")

    @declared_attr
    def template_redacted(cls):
        return db.relationship(
            "TemplateRedacted",
            foreign_keys=[cls.id],
            primaryjoin="TemplateRedacted.template_id == TemplateHistory.id",
        )

    def get_link(self):
        return url_for(
            "v2_template.get_template_by_id",
            template_id=self.id,
            version=self.version,
            _external=True,
        )


SNS_PROVIDER = "sns"
PINPOINT_PROVIDER = "pinpoint"
SES_PROVIDER = "ses"

SMS_PROVIDERS = [SNS_PROVIDER, PINPOINT_PROVIDER]
EMAIL_PROVIDERS = [SES_PROVIDER]
PROVIDERS = SMS_PROVIDERS + EMAIL_PROVIDERS

NotificationType = Literal["email", "sms", "letter"]
NOTIFICATION_TYPE = [EMAIL_TYPE, SMS_TYPE, LETTER_TYPE]
notification_types = db.Enum(*NOTIFICATION_TYPE, name="notification_type")


class ProviderRates(BaseModel):
    __tablename__ = "provider_rates"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    valid_from = db.Column(db.DateTime, nullable=False)
    rate = db.Column(db.Numeric(), nullable=False)
    provider_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("provider_details.id"),
        index=True,
        nullable=False,
    )
    provider = db.relationship("ProviderDetails", backref=db.backref("provider_rates", lazy="dynamic"))


class ProviderDetails(BaseModel):
    __tablename__ = "provider_details"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    display_name = db.Column(db.String, nullable=False)
    identifier = db.Column(db.String, nullable=False)
    priority = db.Column(db.Integer, nullable=False)
    notification_type = db.Column(notification_types, nullable=False)
    active = db.Column(db.Boolean, default=False, nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)
    created_by_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), index=True, nullable=True)
    created_by = db.relationship("User")
    supports_international = db.Column(db.Boolean, nullable=False, default=False)


class ProviderDetailsHistory(BaseModel, HistoryModel):
    __tablename__ = "provider_details_history"

    id = db.Column(UUID(as_uuid=True), primary_key=True, nullable=False)
    display_name = db.Column(db.String, nullable=False)
    identifier = db.Column(db.String, nullable=False)
    priority = db.Column(db.Integer, nullable=False)
    notification_type = db.Column(notification_types, nullable=False)
    active = db.Column(db.Boolean, nullable=False)
    version = db.Column(db.Integer, primary_key=True, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)
    created_by_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), index=True, nullable=True)
    created_by = db.relationship("User")
    supports_international = db.Column(db.Boolean, nullable=False, default=False)


JOB_STATUS_PENDING = "pending"
JOB_STATUS_IN_PROGRESS = "in progress"
JOB_STATUS_FINISHED = "finished"
JOB_STATUS_SENDING_LIMITS_EXCEEDED = "sending limits exceeded"
JOB_STATUS_SCHEDULED = "scheduled"
JOB_STATUS_CANCELLED = "cancelled"
JOB_STATUS_READY_TO_SEND = "ready to send"
JOB_STATUS_SENT_TO_DVLA = "sent to dvla"
JOB_STATUS_ERROR = "error"
JOB_STATUS_TYPES = [
    JOB_STATUS_PENDING,
    JOB_STATUS_IN_PROGRESS,
    JOB_STATUS_FINISHED,
    JOB_STATUS_SENDING_LIMITS_EXCEEDED,
    JOB_STATUS_SCHEDULED,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_READY_TO_SEND,
    JOB_STATUS_SENT_TO_DVLA,
    JOB_STATUS_ERROR,
]


class JobStatus(BaseModel):
    __tablename__ = "job_status"

    name = db.Column(db.String(255), primary_key=True)


class Job(BaseModel):
    __tablename__ = "jobs"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_file_name = db.Column(db.String, nullable=False)
    service_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("services.id"),
        index=True,
        unique=False,
        nullable=False,
    )
    service = db.relationship("Service", backref=db.backref("jobs", lazy="dynamic"))
    template_id = db.Column(UUID(as_uuid=True), db.ForeignKey("templates.id"), index=True, unique=False)
    template = db.relationship("Template", backref=db.backref("jobs", lazy="dynamic"))
    template_version = db.Column(db.Integer, nullable=False)
    created_at = db.Column(
        db.DateTime,
        index=True,
        unique=False,
        nullable=False,
        default=datetime.datetime.utcnow,
    )
    updated_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=True,
        onupdate=datetime.datetime.utcnow,
    )
    notification_count = db.Column(db.Integer, nullable=False)
    notifications_sent = db.Column(db.Integer, nullable=False, default=0)
    notifications_delivered = db.Column(db.Integer, nullable=False, default=0)
    notifications_failed = db.Column(db.Integer, nullable=False, default=0)

    processing_started = db.Column(db.DateTime, index=True, unique=False, nullable=True)
    processing_finished = db.Column(db.DateTime, index=False, unique=False, nullable=True)
    created_by = db.relationship("User")
    created_by_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), index=True, nullable=True)
    api_key_id = db.Column(UUID(as_uuid=True), db.ForeignKey("api_keys.id"), index=True, nullable=True)
    api_key = db.relationship("ApiKey")
    scheduled_for = db.Column(db.DateTime, index=True, unique=False, nullable=True)
    job_status = db.Column(
        db.String(255),
        db.ForeignKey("job_status.name"),
        index=True,
        nullable=False,
        default="pending",
    )
    archived = db.Column(db.Boolean, nullable=False, default=False)
    sender_id = db.Column(UUID(as_uuid=True), index=False, unique=False, nullable=True)


VERIFY_CODE_TYPES = [EMAIL_TYPE, SMS_TYPE]


class VerifyCode(BaseModel):
    __tablename__ = "verify_codes"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), index=True, nullable=False)
    user = db.relationship("User", backref=db.backref("verify_codes", lazy="dynamic"))
    _code = db.Column(db.String, nullable=False)
    code_type = db.Column(
        db.Enum(*VERIFY_CODE_TYPES, name="verify_code_types"),
        index=False,
        unique=False,
        nullable=False,
    )
    expiry_datetime = db.Column(db.DateTime, nullable=False)
    code_used = db.Column(db.Boolean, default=False)
    created_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=False,
        default=datetime.datetime.utcnow,
    )

    @property
    def code(self):
        raise AttributeError("Code not readable")

    @code.setter
    def code(self, cde):
        self._code = hashpw(cde)

    def check_code(self, cde):
        return check_hash(cde, self._code)


NOTIFICATION_CANCELLED = "cancelled"
NOTIFICATION_CREATED = "created"
NOTIFICATION_SENDING = "sending"
NOTIFICATION_SENT = "sent"
NOTIFICATION_DELIVERED = "delivered"
NOTIFICATION_PENDING = "pending"
NOTIFICATION_FAILED = "failed"
NOTIFICATION_TECHNICAL_FAILURE = "technical-failure"
NOTIFICATION_TEMPORARY_FAILURE = "temporary-failure"
NOTIFICATION_PERMANENT_FAILURE = "permanent-failure"
NOTIFICATION_PROVIDER_FAILURE = "provider-failure"
NOTIFICATION_PENDING_VIRUS_CHECK = "pending-virus-check"
NOTIFICATION_VALIDATION_FAILED = "validation-failed"
NOTIFICATION_VIRUS_SCAN_FAILED = "virus-scan-failed"
NOTIFICATION_RETURNED_LETTER = "returned-letter"
NOTIFICATION_CONTAINS_PII = "pii-check-failed"

NOTIFICATION_STATUS_TYPES_FAILED = [
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_PROVIDER_FAILURE,
    NOTIFICATION_VALIDATION_FAILED,
    NOTIFICATION_VIRUS_SCAN_FAILED,
    NOTIFICATION_RETURNED_LETTER,
    NOTIFICATION_CONTAINS_PII,
    NOTIFICATION_FAILED,
]

NOTIFICATION_STATUS_TYPES_COMPLETED = [
    NOTIFICATION_SENT,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_FAILED,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_RETURNED_LETTER,
    NOTIFICATION_CANCELLED,
]

NOTIFICATION_STATUS_SUCCESS = [NOTIFICATION_SENT, NOTIFICATION_DELIVERED]

NOTIFICATION_STATUS_TYPES_BILLABLE_FOR_LETTERS = [
    NOTIFICATION_SENDING,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_RETURNED_LETTER,
]

NOTIFICATION_STATUS_TYPES_BILLABLE = [
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_FAILED,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_RETURNED_LETTER,
]

NOTIFICATION_STATUS_TYPES = [
    NOTIFICATION_CANCELLED,
    NOTIFICATION_CREATED,
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PENDING,
    NOTIFICATION_FAILED,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_PROVIDER_FAILURE,
    NOTIFICATION_PENDING_VIRUS_CHECK,
    NOTIFICATION_VALIDATION_FAILED,
    NOTIFICATION_VIRUS_SCAN_FAILED,
    NOTIFICATION_RETURNED_LETTER,
    NOTIFICATION_CONTAINS_PII,
]

NOTIFICATION_STATUS_TYPES_NON_BILLABLE = list(set(NOTIFICATION_STATUS_TYPES) - set(NOTIFICATION_STATUS_TYPES_BILLABLE))

NOTIFICATION_STATUS_TYPES_ENUM = db.Enum(*NOTIFICATION_STATUS_TYPES, name="notify_status_type")

NOTIFICATION_STATUS_LETTER_ACCEPTED = "accepted"
NOTIFICATION_STATUS_LETTER_RECEIVED = "received"

DVLA_RESPONSE_STATUS_SENT = "Sent"

FIRST_CLASS = "first"
SECOND_CLASS = "second"
POSTAGE_TYPES = [FIRST_CLASS, SECOND_CLASS]
RESOLVE_POSTAGE_FOR_FILE_NAME = {FIRST_CLASS: 1, SECOND_CLASS: 2}

# Bounce types
NOTIFICATION_HARD_BOUNCE = "hard-bounce"
NOTIFICATION_SOFT_BOUNCE = "soft-bounce"
NOTIFICATION_UNKNOWN_BOUNCE = "unknown-bounce"
# List
NOTIFICATION_FEEDBACK_TYPES = [NOTIFICATION_HARD_BOUNCE, NOTIFICATION_SOFT_BOUNCE, NOTIFICATION_UNKNOWN_BOUNCE]

# Hard bounce sub-types
NOTIFICATION_HARD_GENERAL = "general"
NOTIFICATION_HARD_NOEMAIL = "no-email"
NOTIFICATION_HARD_SUPPRESSED = "suppressed"
NOTIFICATION_HARD_ONACCOUNTSUPPRESSIONLIST = "on-account-suppression-list"
# List
NOTIFICATION_HARD_BOUNCE_TYPES = [
    NOTIFICATION_HARD_GENERAL,
    NOTIFICATION_HARD_NOEMAIL,
    NOTIFICATION_HARD_SUPPRESSED,
    NOTIFICATION_HARD_ONACCOUNTSUPPRESSIONLIST,
]

# Soft bounce sub-types
NOTIFICATION_SOFT_GENERAL = "general"
NOTIFICATION_SOFT_MAILBOXFULL = "mailbox-full"
NOTIFICATION_SOFT_MESSAGETOOLARGE = "message-too-large"
NOTIFICATION_SOFT_CONTENTREJECTED = "content-rejected"
NOTIFICATION_SOFT_ATTACHMENTREJECTED = "attachment-rejected"
# List
NOTIFICATION_SOFT_BOUNCE_TYPES = [
    NOTIFICATION_SOFT_GENERAL,
    NOTIFICATION_SOFT_MAILBOXFULL,
    NOTIFICATION_SOFT_MESSAGETOOLARGE,
    NOTIFICATION_SOFT_CONTENTREJECTED,
    NOTIFICATION_SOFT_ATTACHMENTREJECTED,
]
NOTIFICATION_UNKNOWN_BOUNCE_SUBTYPE = "unknown-bounce-subtype"


class NotificationStatusTypes(BaseModel):
    __tablename__ = "notification_status_types"

    name = db.Column(db.String(), primary_key=True)


class Notification(BaseModel):
    __tablename__ = "notifications"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    to = db.Column(db.SensitiveString, nullable=False)
    normalised_to = db.Column(db.SensitiveString, nullable=True)
    job_id = db.Column(UUID(as_uuid=True), db.ForeignKey("jobs.id"), index=True, unique=False)
    job = db.relationship("Job", backref=db.backref("notifications", lazy="dynamic"))
    job_row_number = db.Column(db.Integer, nullable=True)
    service_id = db.Column(UUID(as_uuid=True), db.ForeignKey("services.id"), index=True, unique=False)
    service = db.relationship("Service")
    template_id = db.Column(UUID(as_uuid=True), index=True, unique=False)
    template_version = db.Column(db.Integer, nullable=False)
    template = db.relationship("TemplateHistory")
    api_key_id = db.Column(UUID(as_uuid=True), db.ForeignKey("api_keys.id"), index=True, unique=False)
    api_key = db.relationship("ApiKey")
    key_type = db.Column(
        db.String,
        db.ForeignKey("key_types.name"),
        index=True,
        unique=False,
        nullable=False,
    )
    billable_units = db.Column(db.Integer, nullable=False, default=0)
    notification_type = db.Column(notification_types, index=True, nullable=False)
    created_at = db.Column(db.DateTime, index=True, unique=False, nullable=False)
    sent_at = db.Column(db.DateTime, index=False, unique=False, nullable=True)
    sent_by = db.Column(db.String, nullable=True)
    updated_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=True,
        onupdate=datetime.datetime.utcnow,
    )
    status = db.Column(
        "notification_status",
        db.String,
        db.ForeignKey("notification_status_types.name"),
        index=True,
        nullable=True,
        default="created",
        key="status",  # http://docs.sqlalchemy.org/en/latest/core/metadata.html#sqlalchemy.schema.Column
    )
    reference = db.Column(db.String, nullable=True, index=True)
    client_reference = db.Column(db.String, index=True, nullable=True)
    _personalisation = db.Column(db.SensitiveString, nullable=True)

    scheduled_notification = db.relationship("ScheduledNotification", uselist=False, back_populates="notification")

    client_reference = db.Column(db.String, index=True, nullable=True)

    international = db.Column(db.Boolean, nullable=False, default=False)
    phone_prefix = db.Column(db.String, nullable=True)
    rate_multiplier = db.Column(db.Float(asdecimal=False), nullable=True)

    created_by = db.relationship("User")
    created_by_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=True)

    reply_to_text = db.Column(db.String, nullable=True)

    postage = db.Column(db.String, nullable=True)
    provider_response = db.Column(db.Text, nullable=True)
    queue_name = db.Column(db.Text, nullable=True)

    # feedback columns
    feedback_type = db.Column(db.String, nullable=True)
    feedback_subtype = db.Column(db.String, nullable=True)
    ses_feedback_id = db.Column(db.String, nullable=True)
    ses_feedback_date = db.Column(db.DateTime, nullable=True)
    feedback_reason = db.Column(db.String, nullable=True)

    # SMS columns
    sms_total_message_price = db.Column(db.Numeric(), nullable=True)
    sms_total_carrier_fee = db.Column(db.Numeric(), nullable=True)
    sms_iso_country_code = db.Column(db.String(2), nullable=True)
    sms_carrier_name = db.Column(db.String(255), nullable=True)
    sms_message_encoding = db.Column(db.String(7), nullable=True)
    sms_origination_phone_number = db.Column(db.String(255), nullable=True)

    CheckConstraint(
        """
        CASE WHEN notification_type = 'letter' THEN
            postage is not null and postage in ('first', 'second')
        ELSE
            postage is null
        END
    """
    )

    __table_args__: Iterable[Any] = (
        db.ForeignKeyConstraint(
            ["template_id", "template_version"],
            ["templates_history.id", "templates_history.version"],
        ),
        {},
    )

    @property
    def personalisation(self):
        if self._personalisation:
            return signer_personalisation.verify(self._personalisation)
        return {}

    @personalisation.setter
    def personalisation(self, personalisation):
        self._personalisation = signer_personalisation.sign(personalisation or {})

    def completed_at(self):
        if self.status in NOTIFICATION_STATUS_TYPES_COMPLETED:
            return self.updated_at.strftime(DATETIME_FORMAT)

        return None

    def sends_with_custom_number(self):
        sender = self.reply_to_text
        return self.notification_type == SMS_TYPE and sender and sender[0] == "+"

    @staticmethod
    def substitute_status(status_or_statuses):
        """
        static function that takes a status or list of statuses and substitutes our new failure types if it finds
        the deprecated one

        > IN
        'failed'

        < OUT
        ['technical-failure', 'temporary-failure', 'permanent-failure']

        -

        > IN
        ['failed', 'created', 'accepted']

        < OUT
        ['technical-failure', 'temporary-failure', 'permanent-failure', 'created', 'sending']


        -

        > IN
        'delivered'

        < OUT
        ['received']

        :param status_or_statuses: a single status or list of statuses
        :return: a single status or list with the current failure statuses substituted for 'failure'
        """

        def _substitute_status_str(_status):
            return (
                NOTIFICATION_STATUS_TYPES_FAILED
                if _status == NOTIFICATION_FAILED
                else [NOTIFICATION_CREATED, NOTIFICATION_SENDING]
                if _status == NOTIFICATION_STATUS_LETTER_ACCEPTED
                else NOTIFICATION_DELIVERED
                if _status == NOTIFICATION_STATUS_LETTER_RECEIVED
                else [_status]
            )

        def _substitute_status_seq(_statuses):
            return list(set(itertools.chain.from_iterable(_substitute_status_str(status) for status in _statuses)))

        if isinstance(status_or_statuses, str):
            return _substitute_status_str(status_or_statuses)
        return _substitute_status_seq(status_or_statuses)

    @property
    def content(self):
        from app.utils import get_template_instance

        template_object = get_template_instance(self.template.__dict__, self.personalisation)
        return str(template_object)

    @property
    def subject(self):
        from app.utils import get_template_instance

        if self.notification_type != SMS_TYPE:
            template_object = get_template_instance(self.template.__dict__, self.personalisation)
            return template_object.subject

    @property
    def formatted_status(self):
        def _getStatusByBounceSubtype():
            """Return the status of a notification based on the bounce sub type"""
            # note: if this function changes, update the report query in app/report/utils.py::build_notifications_query
            if self.feedback_subtype:
                return {
                    "suppressed": "Blocked",
                    "on-account-suppression-list": "Blocked",
                }.get(self.feedback_subtype, "No such address")
            else:
                return "No such address"

        def _get_sms_status_by_feedback_reason():
            """Return the status of a notification based on the feedback reason"""
            # note: if this function changes, update the report query in app/report/utils.py::build_notifications_query
            if self.feedback_reason:
                return {
                    "NO_ORIGINATION_IDENTITIES_FOUND": "Can't send to this international number",
                    "DESTINATION_COUNTRY_BLOCKED": "Can't send to this international number",
                }.get(self.feedback_reason, "No such number")
            else:
                return "No such number"

        return {
            "email": {
                **EMAIL_STATUS_FORMATTED,
                "permanent-failure": _getStatusByBounceSubtype(),
            },
            "sms": {
                **SMS_STATUS_FORMATTED,
                "provider-failure": _get_sms_status_by_feedback_reason(),
            },
            "letter": {
                "technical-failure": "Technical failure",
                "sending": "Accepted",
                "created": "Accepted",
                "delivered": "Received",
                "returned-letter": "Returned",
            },
        }[self.template.template_type].get(self.status, self.status)

    def get_letter_status(self):
        """
        Return the notification_status, as we should present for letters. The distinction between created and sending is
        a bit more confusing for letters, not to mention that there's no concept of temporary or permanent failure yet.


        """
        # this should only ever be called for letter notifications - it makes no sense otherwise and I'd rather not
        # get the two code flows mixed up at all
        assert self.notification_type == LETTER_TYPE

        if self.status in [NOTIFICATION_CREATED, NOTIFICATION_SENDING]:
            return NOTIFICATION_STATUS_LETTER_ACCEPTED
        elif self.status in [NOTIFICATION_DELIVERED, NOTIFICATION_RETURNED_LETTER]:
            return NOTIFICATION_STATUS_LETTER_RECEIVED
        else:
            # Currently can only be technical-failure OR pending-virus-check OR validation-failed
            return self.status

    def get_created_by_name(self):
        if self.created_by:
            return self.created_by.name
        else:
            return None

    def get_created_by_email_address(self):
        if self.created_by:
            return self.created_by.email_address
        else:
            return None

    def serialize_for_csv(self) -> dict:
        created_at_in_bst = convert_utc_to_local_timezone(self.created_at)
        serialized = {
            "row_number": "" if self.job_row_number is None else self.job_row_number + 1,
            "recipient": self.to,
            "template_name": self.template.name,
            "template_type": self.template.template_type,
            "job_name": self.job.original_file_name if self.job else "",
            "status": self.formatted_status,
            "created_at": created_at_in_bst.strftime("%Y-%m-%d %H:%M:%S"),
            "created_by_name": self.get_created_by_name(),
            "created_by_email_address": self.get_created_by_email_address(),
        }

        return serialized

    def serialize(self) -> dict:
        template_dict = {
            "version": self.template.version,
            "id": self.template.id,
            "uri": self.template.get_link(),
        }

        serialized = {
            "id": self.id,
            "reference": self.client_reference,
            "email_address": self.to if self.notification_type == EMAIL_TYPE else None,
            "phone_number": self.to if self.notification_type == SMS_TYPE else None,
            "line_1": None,
            "line_2": None,
            "line_3": None,
            "line_4": None,
            "line_5": None,
            "line_6": None,
            "postcode": None,
            "type": self.notification_type,
            "status": self.get_letter_status() if self.notification_type == LETTER_TYPE else self.status,
            "status_description": self.formatted_status,
            "provider_response": self.provider_response,
            "template": template_dict,
            "body": self.content,
            "subject": self.subject,
            "created_at": self.created_at.strftime(DATETIME_FORMAT),
            "created_by_name": self.get_created_by_name(),
            "sent_at": self.sent_at.strftime(DATETIME_FORMAT) if self.sent_at else None,
            "completed_at": self.completed_at(),
            "scheduled_for": (
                convert_local_timezone_to_utc(self.scheduled_notification.scheduled_for).strftime(DATETIME_FORMAT)
                if self.scheduled_notification
                else None
            ),
            "postage": self.postage,
        }

        if self.notification_type == LETTER_TYPE:
            col = Columns(self.personalisation)
            serialized["line_1"] = col.get("address_line_1")
            serialized["line_2"] = col.get("address_line_2")
            serialized["line_3"] = col.get("address_line_3")
            serialized["line_4"] = col.get("address_line_4")
            serialized["line_5"] = col.get("address_line_5")
            serialized["line_6"] = col.get("address_line_6")
            serialized["postcode"] = col.get("postcode")
            serialized["estimated_delivery"] = get_letter_timings(
                serialized["created_at"], postage=self.postage
            ).earliest_delivery.strftime(DATETIME_FORMAT)

        return serialized


class NotificationHistory(BaseModel, HistoryModel):
    __tablename__ = "notification_history"

    id = db.Column(UUID(as_uuid=True), primary_key=True)
    job_id = db.Column(UUID(as_uuid=True), db.ForeignKey("jobs.id"), index=True, unique=False)
    job = db.relationship("Job")
    job_row_number = db.Column(db.Integer, nullable=True)
    service_id = db.Column(UUID(as_uuid=True), db.ForeignKey("services.id"), index=True, unique=False)
    service = db.relationship("Service")
    template_id = db.Column(UUID(as_uuid=True), index=True, unique=False)
    template_version = db.Column(db.Integer, nullable=False)
    api_key_id = db.Column(UUID(as_uuid=True), db.ForeignKey("api_keys.id"), index=True, unique=False)
    api_key = db.relationship("ApiKey")
    key_type = db.Column(
        db.String,
        db.ForeignKey("key_types.name"),
        index=True,
        unique=False,
        nullable=False,
    )
    billable_units = db.Column(db.Integer, nullable=False, default=0)
    notification_type = db.Column(notification_types, index=True, nullable=False)
    created_at = db.Column(db.DateTime, index=True, unique=False, nullable=False)
    sent_at = db.Column(db.DateTime, index=False, unique=False, nullable=True)
    sent_by = db.Column(db.String, nullable=True)
    updated_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=True,
        onupdate=datetime.datetime.utcnow,
    )
    status = db.Column(
        "notification_status",
        db.String,
        db.ForeignKey("notification_status_types.name"),
        index=True,
        nullable=True,
        default="created",
        key="status",  # http://docs.sqlalchemy.org/en/latest/core/metadata.html#sqlalchemy.schema.Column
    )
    reference = db.Column(db.String, nullable=True, index=True)
    client_reference = db.Column(db.String, nullable=True)

    international = db.Column(db.Boolean, nullable=False, default=False)
    phone_prefix = db.Column(db.String, nullable=True)
    rate_multiplier = db.Column(db.Float(asdecimal=False), nullable=True)

    created_by_id = db.Column(UUID(as_uuid=True), nullable=True)

    postage = db.Column(db.String, nullable=True)
    queue_name = db.Column(db.Text, nullable=True)

    # feedback columns
    feedback_type = db.Column(db.String, nullable=True)
    feedback_subtype = db.Column(db.String, nullable=True)
    ses_feedback_id = db.Column(db.String, nullable=True)
    ses_feedback_date = db.Column(db.DateTime, nullable=True)

    # SMS columns
    sms_total_message_price = db.Column(db.Numeric(), nullable=True)
    sms_total_carrier_fee = db.Column(db.Numeric(), nullable=True)
    sms_iso_country_code = db.Column(db.String(2), nullable=True)
    sms_carrier_name = db.Column(db.String(255), nullable=True)
    sms_message_encoding = db.Column(db.String(7), nullable=True)
    sms_origination_phone_number = db.Column(db.String(255), nullable=True)

    CheckConstraint(
        """
        CASE WHEN notification_type = 'letter' THEN
            postage is not null and postage in ('first', 'second')
        ELSE
            postage is null
        END
    """
    )

    __table_args__: Iterable[Any] = (
        db.ForeignKeyConstraint(
            ["template_id", "template_version"],
            ["templates_history.id", "templates_history.version"],
        ),
        {},
    )

    @classmethod
    def from_original(cls, notification):
        history = super().from_original(notification)
        history.status = notification.status
        return history

    def update_from_original(self, original):
        super().update_from_original(original)
        self.status = original.status


class ScheduledNotification(BaseModel):
    __tablename__ = "scheduled_notifications"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    notification_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("notifications.id"),
        index=True,
        nullable=False,
    )
    notification = db.relationship("Notification", uselist=False, back_populates="scheduled_notification")
    scheduled_for = db.Column(db.DateTime, index=False, nullable=False)
    pending = db.Column(db.Boolean, nullable=False, default=True)


INVITE_PENDING = "pending"
INVITE_ACCEPTED = "accepted"
INVITE_CANCELLED = "cancelled"
INVITED_USER_STATUS_TYPES = [INVITE_PENDING, INVITE_ACCEPTED, INVITE_CANCELLED]


class InviteStatusType(BaseModel):
    __tablename__ = "invite_status_type"

    name = db.Column(db.String, primary_key=True)


class InvitedUser(BaseModel):
    __tablename__ = "invited_users"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_address = db.Column(db.String(255), nullable=False)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), index=True, nullable=False)
    from_user = db.relationship("User")
    service_id = db.Column(UUID(as_uuid=True), db.ForeignKey("services.id"), index=True, unique=False)
    service = db.relationship("Service")
    created_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=False,
        default=datetime.datetime.utcnow,
    )
    status = db.Column(
        db.Enum(*INVITED_USER_STATUS_TYPES, name="invited_users_status_types"),
        nullable=False,
        default=INVITE_PENDING,
    )
    permissions = db.Column(db.String, nullable=False)
    auth_type = db.Column(
        db.String,
        db.ForeignKey("auth_type.name"),
        index=True,
        nullable=False,
        default=EMAIL_AUTH_TYPE,
    )
    folder_permissions = db.Column(JSONB(none_as_null=True), nullable=False, default=[])

    # would like to have used properties for this but haven't found a way to make them
    # play nice with marshmallow yet
    def get_permissions(self):
        return self.permissions.split(",")


class InvitedOrganisationUser(BaseModel):
    __tablename__ = "invited_organisation_users"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_address = db.Column(db.String(255), nullable=False)
    invited_by_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)
    invited_by = db.relationship("User")
    organisation_id = db.Column(UUID(as_uuid=True), db.ForeignKey("organisation.id"), nullable=False)
    organisation = db.relationship("Organisation")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    status = db.Column(
        db.String,
        db.ForeignKey("invite_status_type.name"),
        nullable=False,
        default=INVITE_PENDING,
    )

    def serialize(self) -> dict:
        return {
            "id": str(self.id),
            "email_address": self.email_address,
            "invited_by": str(self.invited_by_id),
            "organisation": str(self.organisation_id),
            "created_at": self.created_at.strftime(DATETIME_FORMAT),
            "status": self.status,
        }


# Service Permissions
PermissionType = Literal[
    "manage_users",
    "manage_templates",
    "manage_settings",
    "send_texts",
    "send_emails",
    "send_letters",
    "manage_api_keys",
    "platform_admin",
    "view_activity",
]

MANAGE_USERS = "manage_users"
MANAGE_TEMPLATES = "manage_templates"
MANAGE_SETTINGS = "manage_settings"
SEND_TEXTS = "send_texts"
SEND_EMAILS = "send_emails"
SEND_LETTERS = "send_letters"
MANAGE_API_KEYS = "manage_api_keys"
PLATFORM_ADMIN = "platform_admin"
VIEW_ACTIVITY = "view_activity"

# List of permissions
PERMISSION_LIST = [
    MANAGE_USERS,
    MANAGE_TEMPLATES,
    MANAGE_SETTINGS,
    SEND_TEXTS,
    SEND_EMAILS,
    SEND_LETTERS,
    MANAGE_API_KEYS,
    PLATFORM_ADMIN,
    VIEW_ACTIVITY,
]


class Permission(BaseModel):
    __tablename__ = "permissions"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Service id is optional, if the service is omitted we will assume the permission is not service specific.
    service_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("services.id"),
        index=True,
        unique=False,
        nullable=True,
    )
    service = db.relationship("Service")
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), index=True, nullable=False)
    user = db.relationship("User")
    permission: PermissionType = db.Column(
        db.Enum(*PERMISSION_LIST, name="permission_types"),
        index=False,
        unique=False,
        nullable=False,
    )
    created_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=False,
        default=datetime.datetime.utcnow,
    )

    __table_args__ = (UniqueConstraint("service_id", "user_id", "permission", name="uix_service_user_permission"),)


class Event(BaseModel):
    __tablename__ = "events"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=False,
        default=datetime.datetime.utcnow,
    )
    data = db.Column(JSON, nullable=False)


class Rate(BaseModel):
    __tablename__ = "rates"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    valid_from = db.Column(db.DateTime, nullable=False)
    rate = db.Column(db.Float(asdecimal=False), nullable=False)
    notification_type = db.Column(notification_types, index=True, nullable=False)

    def __str__(self):
        the_string = "{}".format(self.rate)
        the_string += " {}".format(self.notification_type)
        the_string += " {}".format(self.valid_from)
        return the_string


class InboundSms(BaseModel):
    __tablename__ = "inbound_sms"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    service_id = db.Column(UUID(as_uuid=True), db.ForeignKey("services.id"), index=True, nullable=False)
    service = db.relationship("Service", backref="inbound_sms")

    notify_number = db.Column(db.String, nullable=False)  # the service's number, that the msg was sent to
    user_number = db.Column(db.String, nullable=False, index=True)  # the end user's number, that the msg was sent from
    provider_date = db.Column(db.DateTime)
    provider_reference = db.Column(db.String)
    provider = db.Column(db.String, nullable=False)
    _content = db.Column("content", db.String, nullable=False)

    @property
    def content(self):
        return signer_inbound_sms.verify(self._content)

    @content.setter
    def content(self, content):
        self._content = signer_inbound_sms.sign(content)

    def serialize(self) -> dict:
        return {
            "id": str(self.id),
            "created_at": self.created_at.strftime(DATETIME_FORMAT),
            "service_id": str(self.service_id),
            "notify_number": self.notify_number,
            "user_number": self.user_number,
            "content": self.content,
        }


class LetterRate(BaseModel):
    __tablename__ = "letter_rates"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=True)
    sheet_count = db.Column(db.Integer, nullable=False)  # double sided sheet
    rate = db.Column(db.Numeric(), nullable=False)
    crown = db.Column(db.Boolean, nullable=False)
    post_class = db.Column(db.String, nullable=False)


class ServiceEmailReplyTo(BaseModel):
    __tablename__ = "service_email_reply_to"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    service_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("services.id"),
        unique=False,
        index=True,
        nullable=False,
    )
    service = db.relationship(Service, backref=db.backref("reply_to_email_addresses"))

    email_address = db.Column(db.Text, nullable=False, index=False, unique=False)
    is_default = db.Column(db.Boolean, nullable=False, default=True)
    archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)

    def serialize(self) -> dict:
        return {
            "id": str(self.id),
            "service_id": str(self.service_id),
            "email_address": self.email_address,
            "is_default": self.is_default,
            "archived": self.archived,
            "created_at": self.created_at.strftime(DATETIME_FORMAT),
            "updated_at": self.updated_at.strftime(DATETIME_FORMAT) if self.updated_at else None,
        }


class ServiceLetterContact(BaseModel):
    __tablename__ = "service_letter_contacts"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    service_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("services.id"),
        unique=False,
        index=True,
        nullable=False,
    )
    service = db.relationship(Service, backref=db.backref("letter_contacts"))

    contact_block = db.Column(db.Text, nullable=False, index=False, unique=False)
    is_default = db.Column(db.Boolean, nullable=False, default=True)
    archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)

    def serialize(self) -> dict:
        return {
            "id": str(self.id),
            "service_id": str(self.service_id),
            "contact_block": self.contact_block,
            "is_default": self.is_default,
            "archived": self.archived,
            "created_at": self.created_at.strftime(DATETIME_FORMAT),
            "updated_at": self.updated_at.strftime(DATETIME_FORMAT) if self.updated_at else None,
        }


class AuthType(BaseModel):
    __tablename__ = "auth_type"

    name = db.Column(db.String, primary_key=True)


class DailySortedLetter(BaseModel):
    __tablename__ = "daily_sorted_letter"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    billing_day = db.Column(db.Date, nullable=False, index=True)
    file_name = db.Column(db.String, nullable=True, index=True)
    unsorted_count = db.Column(db.Integer, nullable=False, default=0)
    sorted_count = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)

    __table_args__ = (UniqueConstraint("file_name", "billing_day", name="uix_file_name_billing_day"),)


class FactBilling(BaseModel):
    __tablename__ = "ft_billing"

    bst_date = db.Column(db.Date, nullable=False, primary_key=True, index=True)
    template_id = db.Column(UUID(as_uuid=True), nullable=False, primary_key=True, index=True)
    service_id = db.Column(UUID(as_uuid=True), nullable=False, primary_key=True, index=True)
    notification_type = db.Column(db.Text, nullable=False, primary_key=True)
    provider = db.Column(db.Text, nullable=False, primary_key=True)
    rate_multiplier = db.Column(db.Integer(), nullable=False, primary_key=True)
    international = db.Column(db.Boolean, nullable=False, primary_key=True)
    rate = db.Column(db.Numeric(), nullable=False, primary_key=True)
    postage = db.Column(db.String, nullable=False, primary_key=True)
    billable_units = db.Column(db.Integer(), nullable=True)
    notifications_sent = db.Column(db.Integer(), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)


class DateTimeDimension(BaseModel):
    __tablename__ = "dm_datetime"
    bst_date = db.Column(db.Date, nullable=False, primary_key=True, index=True)
    year = db.Column(db.Integer(), nullable=False)
    month = db.Column(db.Integer(), nullable=False)
    month_name = db.Column(db.Text(), nullable=False)
    day = db.Column(db.Integer(), nullable=False)
    bst_day = db.Column(db.Integer(), nullable=False)
    day_of_year = db.Column(db.Integer(), nullable=False)
    week_day_name = db.Column(db.Text(), nullable=False)
    calendar_week = db.Column(db.Integer(), nullable=False)
    quartal = db.Column(db.Text(), nullable=False)
    year_quartal = db.Column(db.Text(), nullable=False)
    year_month = db.Column(db.Text(), nullable=False)
    year_calendar_week = db.Column(db.Text(), nullable=False)
    financial_year = db.Column(db.Integer(), nullable=False)
    utc_daytime_start = db.Column(db.DateTime, nullable=False)
    utc_daytime_end = db.Column(db.DateTime, nullable=False)


Index("ix_dm_datetime_yearmonth", DateTimeDimension.year, DateTimeDimension.month)


class FactNotificationStatus(BaseModel):
    __tablename__ = "ft_notification_status"

    bst_date = db.Column(db.Date, index=True, primary_key=True, nullable=False)
    template_id = db.Column(UUID(as_uuid=True), primary_key=True, index=True, nullable=False)
    service_id = db.Column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        nullable=False,
    )
    job_id = db.Column(UUID(as_uuid=True), primary_key=True, index=True, nullable=False)
    notification_type = db.Column(db.Text, primary_key=True, nullable=False)
    key_type = db.Column(db.Text, primary_key=True, nullable=False)
    notification_status = db.Column(db.Text, primary_key=True, nullable=False)
    notification_count = db.Column(db.Integer(), nullable=False)
    billable_units = db.Column(db.Integer(), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)


class Complaint(BaseModel):
    __tablename__ = "complaints"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    notification_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("notification_history.id"),
        index=True,
        nullable=False,
    )
    service_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("services.id"),
        unique=False,
        index=True,
        nullable=False,
    )
    service = db.relationship(Service, backref=db.backref("complaints"))
    ses_feedback_id = db.Column(db.Text, nullable=True)
    complaint_type = db.Column(db.Text, nullable=True)
    complaint_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    def serialize(self) -> dict:
        return {
            "id": str(self.id),
            "notification_id": str(self.notification_id),
            "service_id": str(self.service_id),
            "service_name": self.service.name,
            "ses_feedback_id": str(self.ses_feedback_id),
            "complaint_type": self.complaint_type,
            "complaint_date": self.complaint_date.strftime(DATETIME_FORMAT) if self.complaint_date else None,
            "created_at": self.created_at.strftime(DATETIME_FORMAT),
        }


class ServiceDataRetention(BaseModel):
    __tablename__ = "service_data_retention"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("services.id"),
        unique=False,
        index=True,
        nullable=False,
    )
    service = db.relationship(Service, backref=db.backref("service_data_retention"))
    notification_type = db.Column(notification_types, nullable=False)
    days_of_retention = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)

    __table_args__ = (UniqueConstraint("service_id", "notification_type", name="uix_service_data_retention"),)

    def serialize(self) -> dict:
        return {
            "id": str(self.id),
            "service_id": str(self.service_id),
            "service_name": self.service.name,
            "notification_type": self.notification_type,
            "days_of_retention": self.days_of_retention,
            "created_at": self.created_at.strftime(DATETIME_FORMAT),
            "updated_at": self.updated_at.strftime(DATETIME_FORMAT) if self.updated_at else None,
        }


class Fido2Key(BaseModel):
    __tablename__ = "fido2_keys"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("users.id"),
        unique=False,
        index=True,
        nullable=False,
    )
    user = db.relationship(User, backref=db.backref("fido2_keys"))
    name = db.Column(db.String, nullable=False, index=False, unique=False)
    key = db.Column(db.Text, nullable=False, index=False, unique=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)

    def serialize(self) -> dict:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "name": self.name,
            "created_at": self.created_at.strftime(DATETIME_FORMAT),
            "updated_at": self.updated_at.strftime(DATETIME_FORMAT) if self.updated_at else None,
        }


class Fido2Session(BaseModel):
    __tablename__ = "fido2_sessions"
    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("users.id"),
        primary_key=True,
        unique=True,
        index=True,
        nullable=False,
    )
    user = db.relationship(User, backref=db.backref("fido2_sessions"))
    session = db.Column(db.Text, nullable=False, index=False, unique=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)


class LoginEvent(BaseModel):
    __tablename__ = "login_events"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("users.id"),
        unique=False,
        index=True,
        nullable=False,
    )
    user = db.relationship(User, backref=db.backref("login_events"))
    data = db.Column(JSONB(none_as_null=True), nullable=False, default={})
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)

    def serialize(self) -> dict:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "data": self.data,
            "created_at": self.created_at.strftime(DATETIME_FORMAT),
            "updated_at": self.updated_at.strftime(DATETIME_FORMAT) if self.updated_at else None,
        }


class BounceRateStatus(Enum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


class AnnualLimitsData(BaseModel):
    __tablename__ = "annual_limits_data"

    service_id = db.Column(UUID(as_uuid=True), db.ForeignKey("services.id"), primary_key=True)
    time_period = db.Column(db.String, primary_key=True)
    annual_email_limit = db.Column(db.BigInteger, nullable=False)
    annual_sms_limit = db.Column(db.BigInteger, nullable=False)
    notification_type = db.Column(notification_types, nullable=False, primary_key=True)
    notification_count = db.Column(db.BigInteger, nullable=False)

    __table_args__ = (
        # Add the composite unique constraint on service_id, time_period, and notification_type
        UniqueConstraint("service_id", "time_period", "notification_type", name="uix_service_time_notification"),
        # Define the indexes within __table_args__
        db.Index("ix_service_id_notification_type", "service_id", "notification_type"),
        db.Index("ix_service_id_notification_type_time", "time_period", "service_id", "notification_type"),
    )


class ReportStatus(Enum):
    REQUESTED = "requested"
    GENERATING = "generating"
    READY = "ready"
    ERROR = "error"


class ReportType(Enum):
    SMS = "sms"
    EMAIL = "email"
    JOB = "job"


class Report(BaseModel):
    __tablename__ = "reports"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_type = db.Column(db.String(255), nullable=False)  # email, sms, job, other types in future
    requested_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=False,
        default=datetime.datetime.utcnow,
    )
    completed_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=True,
        default=datetime.datetime.utcnow,
    )
    expires_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=True,
        onupdate=datetime.datetime.utcnow,
    )
    requesting_user_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=True
    )  # only set if report is requested by a user
    requesting_user = db.relationship("User")
    service_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("services.id"),
        unique=False,
        index=True,
        nullable=False,
    )
    job_id = db.Column(UUID(as_uuid=True), db.ForeignKey("jobs.id"), nullable=True)  # only set if report is for a bulk job
    url = db.Column(db.String(2000), nullable=True)  # url to download the report from s3
    status = db.Column(db.String(255), nullable=False)
    language = db.Column(db.String(2), nullable=True)

    def serialize(self):
        return {
            "id": str(self.id),
            "report_type": self.report_type,
            "service_id": str(self.service_id),
            "status": self.status,
            "requested_at": self.requested_at.strftime(DATETIME_FORMAT),
            "completed_at": self.completed_at.strftime(DATETIME_FORMAT) if self.completed_at else None,
            "expires_at": self.expires_at.strftime(DATETIME_FORMAT) if self.expires_at else None,
            "url": self.url,
        }
