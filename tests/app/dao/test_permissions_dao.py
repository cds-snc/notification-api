from app.dao.permissions_dao import permission_dao
from app.models import MANAGE_SETTINGS
from tests.app.conftest import create_sample_service


def test_get_permissions_by_user_id_returns_all_permissions(sample_service):
    permissions = permission_dao.get_permissions_by_user_id(user_id=sample_service.users[0].id)
    assert len(permissions) == 8
    assert sorted(
        [
            "manage_users",
            "manage_templates",
            "manage_settings",
            "send_texts",
            "send_emails",
            "send_letters",
            "manage_api_keys",
            "view_activity",
        ]
    ) == sorted([i.permission for i in permissions])


def test_get_permissions_by_user_id_returns_only_active_service(notify_db, notify_db_session, sample_user):
    active_service = create_sample_service(notify_db, notify_db_session, service_name="Active service", user=sample_user)
    inactive_service = create_sample_service(notify_db, notify_db_session, service_name="Inactive service", user=sample_user)
    inactive_service.active = False
    permissions = permission_dao.get_permissions_by_user_id(user_id=sample_user.id)
    assert len(permissions) == 8
    assert active_service in [i.service for i in permissions]
    assert inactive_service not in [i.service for i in permissions]


def test_get_team_members_with_permission(notify_db, notify_db_session, sample_user):
    active_service = create_sample_service(notify_db, notify_db_session, service_name="Active service", user=sample_user)
    
    users_w_permission_1 = permission_dao.get_team_members_with_permission(active_service.id, MANAGE_SETTINGS)
    assert users_w_permission_1 == [sample_user]
    
    permission_dao.remove_user_service_permissions(user=sample_user, service=active_service)
    users_w_permission_2 = permission_dao.get_team_members_with_permission(active_service.id, MANAGE_SETTINGS)
    assert users_w_permission_2 == []
    
    users_w_permission_3 = permission_dao.get_team_members_with_permission(active_service.id, None)
    assert users_w_permission_3 == []
    