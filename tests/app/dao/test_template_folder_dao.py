from sqlalchemy import select

from app.dao.service_user_dao import dao_get_service_user
from app.dao.template_folder_dao import (
    dao_delete_template_folder,
    dao_update_template_folder,
)
from app.models import user_folder_permissions
from tests.app.db import create_template_folder


def test_dao_delete_template_folder_deletes_user_folder_permissions(
    notify_db_session,
    sample_service,
):
    service = sample_service()
    folder = create_template_folder(service)
    folder_id = folder.id
    service_user = dao_get_service_user(service.created_by_id, service.id)
    folder.users = [service_user]

    dao_update_template_folder(folder)
    dao_delete_template_folder(folder)

    stmt = select(user_folder_permissions).where(user_folder_permissions.c.template_folder_id == folder_id)
    assert notify_db_session.session.scalars(stmt).all() == []
