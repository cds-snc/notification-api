import datetime
import uuid

from sqlalchemy import CheckConstraint, select
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from app import DATETIME_FORMAT
from app.db import db
from app.encryption import (
    hashpw,
    check_hash
)
from .identity_provider_identifier import IdentityProviderIdentifier


SMS_AUTH_TYPE = 'sms_auth'
EMAIL_AUTH_TYPE = 'email_auth'
USER_AUTH_TYPE = [SMS_AUTH_TYPE, EMAIL_AUTH_TYPE]


class User(db.Model):
    __tablename__ = 'users'

    def __init__(self, idp_name: str = None, idp_id: str = None, **kwargs):
        super().__init__(**kwargs)
        if idp_name and idp_id:
            self.idp_ids.append(IdentityProviderIdentifier(self.id, idp_name, str(idp_id)))

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String, nullable=False, index=True, unique=False)
    email_address = db.Column(db.String(255), nullable=False, index=True, unique=True)
    created_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=False,
        default=datetime.datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        index=False,
        unique=False,
        nullable=True,
        onupdate=datetime.datetime.utcnow)
    _password = db.Column(db.String, index=False, unique=False, nullable=True)
    mobile_number = db.Column(db.String, index=False, unique=False, nullable=True)
    password_changed_at = db.Column(db.DateTime, index=False, unique=False, nullable=True,
                                    default=datetime.datetime.utcnow)
    logged_in_at = db.Column(db.DateTime, nullable=True)
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    state = db.Column(db.String, nullable=False, default='pending')
    platform_admin = db.Column(db.Boolean, nullable=False, default=False)
    current_session_id = db.Column(UUID(as_uuid=True), nullable=True)
    auth_type = db.Column(
        db.String, db.ForeignKey('auth_type.name'), index=True, nullable=True, default=EMAIL_AUTH_TYPE)
    blocked = db.Column(db.Boolean, nullable=False, default=False)
    additional_information = db.Column(JSONB(none_as_null=True), nullable=True, default={})
    _identity_provider_user_id = db.Column("identity_provider_user_id", db.String,
                                           index=True, unique=True, nullable=True)
    idp_ids = db.relationship('IdentityProviderIdentifier', cascade='all, delete-orphan')

    # a mobile number must be provided if using sms auth
    CheckConstraint(
        sqltext="auth_type != 'sms_auth' or mobile_number is not null",
        name='ck_users_mobile_number_if_sms_auth'
    )

    services = db.relationship(
        'Service',
        secondary='user_to_service',
        backref='users')
    organisations = db.relationship(
        'Organisation',
        secondary='user_to_organisation',
        backref='users')

    @property
    def password(self):
        raise AttributeError("Password not readable")

    @password.setter
    def password(self, password):
        self._password = hashpw(password)

    @hybrid_property
    def identity_provider_user_id(self):
        return self._identity_provider_user_id

    @identity_provider_user_id.setter
    def identity_provider_user_id(self, id):
        self._identity_provider_user_id = id
        if id:
            self.idp_ids.append(IdentityProviderIdentifier(self.id, 'github', id))

    @classmethod
    def find_by_idp(cls, idp_name: str, idp_id: str) -> 'User':
        stmt = select(cls).join(
            cls.idp_ids
        ).where(
            IdentityProviderIdentifier.idp_name == idp_name,
            IdentityProviderIdentifier.idp_id == str(idp_id)
        )

        return db.session.scalars(stmt).one()

    def save_to_db(self) -> None:
        db.session.add(self)
        db.session.commit()

    def add_idp(self, idp_name: str, idp_id: str) -> None:
        if not idp_name or not idp_id:
            raise ValueError("Must provide IDP name and id")
        self.idp_ids.append(IdentityProviderIdentifier(self.id, idp_name, str(idp_id)))

    def check_password(self, password):
        if self.blocked:
            return False

        return check_hash(password, self._password)

    def get_permissions(self, service_id=None):
        from app.dao.permissions_dao import permission_dao

        if service_id:
            return [
                x.permission for x in permission_dao.get_permissions_by_user_id_and_service_id(self.id, service_id)
            ]

        retval = {}
        for x in permission_dao.get_permissions_by_user_id(self.id):
            service_id = str(x.service_id)
            if service_id not in retval:
                retval[service_id] = []
            retval[service_id].append(x.permission)
        return retval

    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'email_address': self.email_address,
            'auth_type': self.auth_type,
            'current_session_id': self.current_session_id,
            'failed_login_count': self.failed_login_count,
            'logged_in_at': self.logged_in_at.strftime(DATETIME_FORMAT) if self.logged_in_at else None,
            'mobile_number': self.mobile_number,
            'organisations': [x.id for x in self.organisations if x.active],
            'password_changed_at': (
                self.password_changed_at.strftime('%Y-%m-%d %H:%M:%S.%f')
                if self.password_changed_at
                else None
            ),
            'permissions': self.get_permissions(),
            'platform_admin': self.platform_admin,
            'services': [x.id for x in self.services if x.active],
            'state': self.state,
            'blocked': self.blocked,
            'additional_information': self.additional_information,
            'identity_provider_user_id': self.identity_provider_user_id
        }

    def serialize_for_users_list(self):
        return {
            'id': self.id,
            'name': self.name,
            'email_address': self.email_address,
            'mobile_number': self.mobile_number,
        }

    def serialize_for_user_services(self):
        services = [service.serialize_for_user() for service in self.services if service.active]

        return {
            'id': str(self.id),
            'name': self.name,
            'email_address': self.email_address,
            'services': services
        }
