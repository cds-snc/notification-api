import pytest
import uuid
from app.dao.service_user_dao import dao_get_service_user
from app.models import TemplateFolder
from tests.app.conftest import template_folder_cleanup
from tests.app.db import create_template_folder


def test_get_folders_for_service(admin_request, sample_service, sample_template_folder):
    s1 = sample_service()
    s2 = sample_service()

    tf1 = sample_template_folder(service=s1)
    tf2 = sample_template_folder(service=s1)
    sample_template_folder(service=s2)

    resp = admin_request.get('template_folder.get_template_folders_for_service', service_id=tf1.service.id)
    assert set(resp.keys()) == {'template_folders'}
    expected = sorted(
        [
            {
                'id': str(tf1.id),
                'name': tf1.name,
                'service_id': str(tf1.service.id),
                'parent_id': None,
                'users_with_permission': [],
            },
            {
                'id': str(tf2.id),
                'name': tf2.name,
                'service_id': str(tf1.service.id),
                'parent_id': None,
                'users_with_permission': [],
            },
        ],
        key=lambda x: x['id'],
    )
    actual = sorted(resp['template_folders'], key=lambda x: x['id'])

    assert expected == actual


def test_get_folders_for_service_with_no_folders(sample_service, admin_request):
    resp = admin_request.get('template_folder.get_template_folders_for_service', service_id=sample_service().id)
    assert resp == {'template_folders': []}


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_folders_returns_users_with_permission(admin_request, sample_service, sample_user):
    service = sample_service()
    user_1 = sample_user(email=f'{uuid.uuid4()}@va.gov')
    user_2 = sample_user(email=f'{uuid.uuid4()}@va.gov')
    user_3 = sample_user(email=f'{uuid.uuid4()}@va.gov')
    template_folder = create_template_folder(service)

    service.users = [user_1, user_2, user_3]

    service_user_1 = dao_get_service_user(user_1.id, service.id)
    service_user_2 = dao_get_service_user(user_2.id, service.id)

    service_user_1.folders = [template_folder]
    service_user_2.folders = [template_folder]

    resp = admin_request.get('template_folder.get_template_folders_for_service', service_id=service.id)
    users_with_permission = resp['template_folders'][0]['users_with_permission']

    assert len(users_with_permission) == 2
    assert str(user_1.id) in users_with_permission
    assert str(user_2.id) in users_with_permission


@pytest.mark.parametrize('has_parent', [True, False])
def test_create_template_folder(
    notify_db_session,
    admin_request,
    sample_template_folder,
    has_parent,
):
    existing_folder = sample_template_folder()
    parent_id = str(existing_folder.id) if has_parent else None

    resp = admin_request.post(
        'template_folder.create_template_folder',
        service_id=existing_folder.service.id,
        _data={'name': 'foo', 'parent_id': parent_id},
        _expected_status=201,
    )

    try:
        assert resp['data']['name'] == 'foo'
        assert resp['data']['service_id'] == str(existing_folder.service.id)
        assert resp['data']['parent_id'] == parent_id
    finally:
        # Teardown
        template_folder_cleanup([resp['data']['id']], notify_db_session.session)


@pytest.mark.parametrize('has_parent', [True, False])
def test_create_template_folder_sets_user_permissions(
    notify_db_session,
    admin_request,
    sample_template_folder,
    sample_user,
    has_parent,
):
    user_1 = sample_user(email=f'{uuid.uuid4()}@va.gov')
    user_2 = sample_user(email=f'{uuid.uuid4()}@va.gov')
    user_3 = sample_user(email=f'{uuid.uuid4()}@va.gov', state='pending')
    existing_folder = sample_template_folder()
    existing_folder.service.users = [user_1, user_2, user_3]
    service_user_1 = dao_get_service_user(user_1.id, existing_folder.service.id)
    service_user_1.folders = [existing_folder]

    parent_id = str(existing_folder.id) if has_parent else None

    resp = admin_request.post(
        'template_folder.create_template_folder',
        service_id=existing_folder.service.id,
        _data={'name': 'foo', 'parent_id': parent_id},
        _expected_status=201,
    )

    try:
        assert resp['data']['name'] == 'foo'
        assert resp['data']['service_id'] == str(existing_folder.service.id)
        assert resp['data']['parent_id'] == parent_id

        if has_parent:
            assert resp['data']['users_with_permission'] == [str(user_1.id)]
        else:
            assert sorted(resp['data']['users_with_permission']) == sorted([str(user_1.id), str(user_2.id)])
    finally:
        # Teardown
        template_folder_cleanup([resp['data']['id']], notify_db_session.session)


@pytest.mark.parametrize('missing_field', ['name', 'parent_id'])
def test_create_template_folder_fails_if_missing_fields(admin_request, sample_service, missing_field):
    data = {'name': 'foo', 'parent_id': None}
    data.pop(missing_field)

    resp = admin_request.post(
        'template_folder.create_template_folder', service_id=sample_service().id, _data=data, _expected_status=400
    )

    assert resp == {
        'status_code': 400,
        'errors': [{'error': 'ValidationError', 'message': '{} is a required property'.format(missing_field)}],
    }


def test_create_template_folder_fails_if_unknown_parent_id(admin_request, sample_service):
    resp = admin_request.post(
        'template_folder.create_template_folder',
        service_id=sample_service().id,
        _data={'name': 'bar', 'parent_id': str(uuid.uuid4())},
        _expected_status=400,
    )

    assert resp['result'] == 'error'
    assert resp['message'] == 'parent_id not found'


def test_create_template_folder_fails_if_parent_id_from_different_service(
    admin_request, sample_service, sample_template_folder
):
    parent_folder = sample_template_folder()

    resp = admin_request.post(
        'template_folder.create_template_folder',
        service_id=sample_service().id,
        _data={'name': 'bar', 'parent_id': str(parent_folder.id)},
        _expected_status=400,
    )

    assert resp['result'] == 'error'
    assert resp['message'] == 'parent_id not found'


def test_update_template_folder_name(admin_request, sample_template_folder):
    existing_folder = sample_template_folder()

    resp = admin_request.post(
        'template_folder.update_template_folder',
        service_id=existing_folder.service.id,
        template_folder_id=existing_folder.id,
        _data={'name': 'bar'},
    )

    assert resp['data']['name'] == 'bar'
    assert existing_folder.name == 'bar'


def test_update_template_folder_users(admin_request, sample_template_folder, sample_user):
    existing_folder = sample_template_folder()
    user_1 = sample_user(email='notify_1@digital.cabinet-office.gov.uk')
    user_2 = sample_user(email='notify_2@digital.cabinet-office.gov.uk')
    user_3 = sample_user(email='notify_3@digital.cabinet-office.gov.uk')
    existing_folder.service.users += [user_1, user_2, user_3]
    assert len(existing_folder.users) == 0
    response_1 = admin_request.post(
        'template_folder.update_template_folder',
        service_id=existing_folder.service.id,
        template_folder_id=existing_folder.id,
        _data={'name': 'foo', 'users_with_permission': [str(user_1.id)]},
    )

    assert response_1['data']['users_with_permission'] == [str(user_1.id)]
    assert len(existing_folder.users) == 1

    response_2 = admin_request.post(
        'template_folder.update_template_folder',
        service_id=existing_folder.service.id,
        template_folder_id=existing_folder.id,
        _data={'name': 'foo', 'users_with_permission': [str(user_2.id), str(user_3.id)]},
    )

    resp = response_2['data']['users_with_permission']
    expected_users = [str(user_2.id), str(user_3.id)]
    # Compare without altering (can't make a set because it may clean values out)
    assert len([x for x in resp if x in expected_users]) == len(resp)
    assert len(existing_folder.users) == 2


@pytest.mark.parametrize(
    'data, err',
    [
        ({}, 'name is a required property'),
        ({'name': None}, 'name None is not of type string'),
        ({'name': ''}, 'name  is too short'),
    ],
)
def test_update_template_folder_fails_if_missing_name(admin_request, sample_template_folder, data, err):
    existing_folder = sample_template_folder()

    resp = admin_request.post(
        'template_folder.update_template_folder',
        service_id=existing_folder.service.id,
        template_folder_id=existing_folder.id,
        _data=data,
        _expected_status=400,
    )

    assert resp == {'status_code': 400, 'errors': [{'error': 'ValidationError', 'message': err}]}


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_delete_template_folder(admin_request, sample_service):
    service = sample_service()
    existing_folder = create_template_folder(service)

    admin_request.delete(
        'template_folder.delete_template_folder',
        service_id=service.id,
        template_folder_id=existing_folder.id,
    )

    assert TemplateFolder.query.all() == []


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_delete_template_folder_fails_if_folder_has_subfolders(admin_request, sample_service):
    service = sample_service()
    existing_folder = create_template_folder(service)
    create_template_folder(service, parent=existing_folder)  # noqa

    resp = admin_request.delete(
        'template_folder.delete_template_folder',
        service_id=service.id,
        template_folder_id=existing_folder.id,
        _expected_status=400,
    )

    assert resp == {'result': 'error', 'message': 'Folder is not empty'}

    assert TemplateFolder.query.count() == 2


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_delete_template_folder_fails_if_folder_contains_templates(
    admin_request, sample_service, sample_email_template_func
):
    service = sample_service()
    existing_folder = create_template_folder(service)
    sample_email_template_func.folder = existing_folder

    resp = admin_request.delete(
        'template_folder.delete_template_folder',
        service_id=service.id,
        template_folder_id=existing_folder.id,
        _expected_status=400,
    )

    assert resp == {'result': 'error', 'message': 'Folder is not empty'}

    assert TemplateFolder.query.count() == 1


@pytest.mark.parametrize(
    'data',
    [
        {},
        {'templates': None, 'folders': []},
        {'folders': []},
        {'templates': [], 'folders': [None]},
        {'templates': [], 'folders': ['not a uuid']},
    ],
)
def test_move_to_folder_validates_schema(data, admin_request, notify_db_session):
    admin_request.post(
        'template_folder.move_to_template_folder',
        service_id=uuid.uuid4(),
        target_template_folder_id=uuid.uuid4(),
        _data=data,
        _expected_status=400,
    )


def test_move_to_folder_moves_folders_and_templates(
    admin_request, sample_service, sample_template, sample_template_folder
):
    service = sample_service()
    target_folder = sample_template_folder(service=service, name='target')
    f1 = sample_template_folder(service=service, name='f1')
    f2 = sample_template_folder(service=service, name='f2')

    t1 = sample_template(service=service, name=str(uuid.uuid4()), folder=f1)
    t2 = sample_template(service=service, name=str(uuid.uuid4()), folder=f1)
    t3 = sample_template(service=service, name=str(uuid.uuid4()), folder=f2)
    t4 = sample_template(service=service, name=str(uuid.uuid4()), folder=target_folder)

    admin_request.post(
        'template_folder.move_to_template_folder',
        service_id=service.id,
        target_template_folder_id=target_folder.id,
        _data={'templates': [str(t1.id)], 'folders': [str(f1.id)]},
        _expected_status=204,
    )

    assert target_folder.parent is None
    assert f1.parent == target_folder
    assert f2.parent is None  # unchanged

    assert t1.folder == target_folder  # moved out of f1, even though f1 is also being moved
    assert t2.folder == f1  # stays in f1, though f1 has moved
    assert t3.folder == f2  # unchanged
    assert t4.folder == target_folder  # unchanged

    # versions are all unchanged
    assert t1.version == 1
    assert t2.version == 1
    assert t3.version == 1
    assert t4.version == 1


def test_move_to_folder_moves_folders_and_templates_to_top_level_if_no_target(
    admin_request, sample_service, sample_template, sample_template_folder
):
    service = sample_service()
    f1 = sample_template_folder(service=service, name='f1')
    f2 = sample_template_folder(service=service, name='f2', parent=f1)

    t1 = sample_template(service=service, name=str(uuid.uuid4()), folder=f1)
    t2 = sample_template(service=service, name=str(uuid.uuid4()), folder=f1)
    t3 = sample_template(service=service, name=str(uuid.uuid4()), folder=f2)

    admin_request.post(
        'template_folder.move_to_template_folder',
        service_id=service.id,
        target_template_folder_id=None,
        _data={'templates': [str(t1.id)], 'folders': [str(f2.id)]},
        _expected_status=204,
    )

    assert f1.parent is None  # unchanged
    assert f2.parent is None

    assert t1.folder is None  # moved out of f1
    assert t2.folder == f1  # unchanged
    assert t3.folder == f2  # stayed in f2 even though the parent changed


def test_move_to_folder_rejects_folder_from_other_service(admin_request, sample_service, sample_template_folder):
    s1 = sample_service(service_name=str(uuid.uuid4()))
    s2 = sample_service(service_name=str(uuid.uuid4()))

    f2 = sample_template_folder(service=s2)

    response = admin_request.post(
        'template_folder.move_to_template_folder',
        service_id=s1.id,
        target_template_folder_id=None,
        _data={'templates': [], 'folders': [str(f2.id)]},
        _expected_status=400,
    )
    assert response['message'] == 'No folder found with id {} for service {}'.format(f2.id, s1.id)


def test_move_to_folder_rejects_template_from_other_service(admin_request, sample_service, sample_template):
    s1 = sample_service(service_name=str(uuid.uuid4()))
    s2 = sample_service(service_name=str(uuid.uuid4()))

    t2 = sample_template(service=s2)

    response = admin_request.post(
        'template_folder.move_to_template_folder',
        service_id=s1.id,
        target_template_folder_id=None,
        _data={'templates': [str(t2.id)], 'folders': []},
        _expected_status=400,
    )
    assert response['message'] == 'Could not move to folder: No template found with id {} for service {}'.format(
        t2.id, s1.id
    )


def test_move_to_folder_rejects_if_it_would_cause_folder_loop(admin_request, sample_service, sample_template_folder):
    service = sample_service()
    f1 = sample_template_folder(service=service, name='f1')
    target_folder = sample_template_folder(service=service, name='target', parent=f1)

    response = admin_request.post(
        'template_folder.move_to_template_folder',
        service_id=service.id,
        target_template_folder_id=target_folder.id,
        _data={'templates': [], 'folders': [str(f1.id)]},
        _expected_status=400,
    )
    assert response['message'] == 'You cannot move a folder to one of its subfolders'


def test_move_to_folder_itself_is_rejected(admin_request, sample_service, sample_template_folder):
    service = sample_service()
    target_folder = sample_template_folder(service=service, name='target')

    response = admin_request.post(
        'template_folder.move_to_template_folder',
        service_id=service.id,
        target_template_folder_id=target_folder.id,
        _data={'templates': [], 'folders': [str(target_folder.id)]},
        _expected_status=400,
    )
    assert response['message'] == 'You cannot move a folder to itself'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_move_to_folder_skips_archived_templates(admin_request, sample_service, sample_template):
    service = sample_service()
    target_folder = create_template_folder(service)
    other_folder = create_template_folder(service)

    archived_template = sample_template(service=service, archived=True, folder=None)
    unarchived_template = sample_template(service=service, archived=False, folder=other_folder)

    archived_timestamp = archived_template.updated_at

    admin_request.post(
        'template_folder.move_to_template_folder',
        service_id=service.id,
        target_template_folder_id=target_folder.id,
        _data={'templates': [str(archived_template.id), str(unarchived_template.id)], 'folders': []},
        _expected_status=204,
    )

    assert archived_template.updated_at == archived_timestamp
    assert archived_template.folder is None
    assert unarchived_template.folder == target_folder
