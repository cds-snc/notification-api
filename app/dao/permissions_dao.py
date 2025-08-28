from sqlalchemy import delete, select

from app import db
from app.constants import DEFAULT_SERVICE_MANAGEMENT_PERMISSIONS
from app.dao import DAOClass
from app.models import (
    Permission,
    Service,
)


class PermissionDAO(DAOClass):
    class Meta:
        model = Permission

    def add_default_service_permissions_for_user(
        self,
        user,
        service,
    ):
        for name in DEFAULT_SERVICE_MANAGEMENT_PERMISSIONS:
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
    ) -> list[Permission]:
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
    ) -> list[Permission]:
        stmt = (
            select(self.Meta.model)
            .join(self.Meta.model.service)
            .where(self.Meta.model.user_id == user_id, Service.id == service_id, Service.active.is_(True))
        )

        return db.session.scalars(stmt).all()


permission_dao = PermissionDAO()
