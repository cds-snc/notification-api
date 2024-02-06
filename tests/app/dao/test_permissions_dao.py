from app.dao.permissions_dao import permission_dao


def test_get_permissions_by_user_id_returns_all_permissions(sample_service):
    permissions = permission_dao.get_permissions_by_user_id(user_id=sample_service().users[0].id)
    assert len(permissions) == 8
    assert sorted(
        [
            'manage_users',
            'manage_templates',
            'manage_settings',
            'send_texts',
            'send_emails',
            'send_letters',
            'manage_api_keys',
            'view_activity',
        ]
    ) == sorted([i.permission for i in permissions])


def test_get_permissions_by_user_id_returns_only_active_service(sample_user, sample_service):
    user = sample_user()
    active_service = sample_service(user=user, service_name='Active service')
    inactive_service = sample_service(user=user, service_name='Inactive service', active=False)

    permissions = permission_dao.get_permissions_by_user_id(user_id=user.id)
    assert len(permissions) == 8
    assert active_service in [i.service for i in permissions]
    assert inactive_service not in [i.service for i in permissions]
