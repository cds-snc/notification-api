from app import db
from app.dao import DAOClass
from app.models import (
    Permission,
    MANAGE_API_KEYS,
    MANAGE_SETTINGS,
    MANAGE_TEMPLATES,
    MANAGE_USERS,
    SEND_TEXTS,
    SEND_EMAILS,
    SEND_LETTERS,
    Service,
    VIEW_ACTIVITY,
)
from sqlalchemy import delete, select
from typing import List


# Default permissions for a service
default_service_permissions = [
    MANAGE_USERS,
    MANAGE_TEMPLATES,
    MANAGE_SETTINGS,
    SEND_TEXTS,
    SEND_EMAILS,
    SEND_LETTERS,
    MANAGE_API_KEYS,
    VIEW_ACTIVITY,
]


class PermissionDAO(DAOClass):
    class Meta:
        model = Permission

    def add_default_service_permissions_for_user(
        self,
        user,
        service,
    ):
        for name in default_service_permissions:
            permission = Permission(permission=name, user=user, service=service)
            self.create_instance(permission, _commit=False)

    def remove_user_service_permissions(
        self,
        user,
        service,
    ):
        stmt = delete(self.Meta.model).where(self.Meta.model.user == user, self.Meta.model.service == service)
        db.session.execute(stmt)

    def remove_user_service_permissions_for_all_services(
        self,
        user,
    ):
        """
        The deletion is commited in the calling code.
        """

        stmt = delete(self.Meta.model).where(self.Meta.model.user == user)
        db.session.execute(stmt)

    def set_user_service_permission(
        self,
        user,
        service,
        permissions,
        _commit=False,
        replace=False,
    ):
        try:
            if replace:
                self.remove_user_service_permissions(user, service)
            for p in permissions:
                p.user = user
                p.service = service
                self.create_instance(p, _commit=False)
        except Exception as e:
            if _commit:
                db.session.rollback()
            raise e
        else:
            if _commit:
                db.session.commit()

    def get_permissions_by_user_id(
        self,
        user_id,
    ) -> List[Permission]:
        stmt = (
            select(self.Meta.model)
            .join(self.Meta.model.service)
            .where(self.Meta.model.user_id == user_id, Service.active.is_(True))
        )

        return db.session.scalars(stmt).all()

    def get_permissions_by_user_id_and_service_id(
        self,
        user_id,
        service_id,
    ) -> List[Permission]:
        stmt = (
            select(self.Meta.model)
            .join(self.Meta.model.service)
            .where(self.Meta.model.user_id == user_id, Service.id == service_id, Service.active.is_(True))
        )

        return db.session.scalars(stmt).all()


permission_dao = PermissionDAO()
