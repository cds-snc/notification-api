import uuid

from app.dao.organisation_dao import dao_add_service_to_organisation, dao_add_user_to_organisation


def test_get_organisation_by_id(
    admin_request,
    sample_organisation,
):
    org = sample_organisation()

    response = admin_request.get('organisation.get_organisation_by_id', _expected_status=200, organisation_id=org.id)

    assert set(response.keys()) == {
        'id',
        'name',
        'active',
        'crown',
        'organisation_type',
        'agreement_signed',
        'agreement_signed_at',
        'agreement_signed_by_id',
        'agreement_signed_version',
        'agreement_signed_on_behalf_of_name',
        'agreement_signed_on_behalf_of_email_address',
        'email_branding_id',
        'domains',
        'request_to_go_live_notes',
        'count_of_live_services',
    }
    assert response['id'] == str(org.id)
    assert response['name'] == org.name
    assert response['active'] is True
    assert response['crown'] is None
    assert response['organisation_type'] is None
    assert response['agreement_signed'] is None
    assert response['agreement_signed_by_id'] is None
    assert response['agreement_signed_version'] is None
    assert response['email_branding_id'] is None
    assert response['domains'] == []
    assert response['request_to_go_live_notes'] is None
    assert response['count_of_live_services'] == 0
    assert response['agreement_signed_on_behalf_of_name'] is None
    assert response['agreement_signed_on_behalf_of_email_address'] is None


def test_post_update_organisation_raises_400_on_existing_org_name(
    admin_request,
    sample_organisation,
):
    org = sample_organisation()
    data = {'name': sample_organisation().name, 'active': False}

    response = admin_request.post(
        'organisation.update_organisation', _data=data, organisation_id=org.id, _expected_status=400
    )

    assert response['message'] == 'Organisation name already exists'


def test_post_update_organisation_set_mou_doesnt_email_if_no_signed_by(sample_organisation, admin_request, mocker):
    queue_mock = mocker.patch('app.organisation.rest.send_notification_to_queue')

    data = {'agreement_signed': True}

    admin_request.post(
        'organisation.update_organisation', _data=data, organisation_id=sample_organisation().id, _expected_status=204
    )

    assert queue_mock.called is False


def test_post_link_service_to_organisation(
    admin_request,
    sample_service,
    sample_organisation,
):
    data = {'service_id': str(sample_service().id)}

    org = sample_organisation()
    admin_request.post(
        'organisation.link_service_to_organisation', _data=data, organisation_id=org.id, _expected_status=204
    )

    assert len(org.services) == 1


def test_post_link_service_to_another_org(
    admin_request,
    sample_service,
    sample_organisation,
):
    data = {'service_id': str(sample_service().id)}

    org = sample_organisation()
    admin_request.post(
        'organisation.link_service_to_organisation', _data=data, organisation_id=org.id, _expected_status=204
    )

    assert len(org.services) == 1

    new_org = sample_organisation()
    admin_request.post(
        'organisation.link_service_to_organisation', _data=data, organisation_id=new_org.id, _expected_status=204
    )
    assert not org.services
    assert len(new_org.services) == 1


def test_post_link_service_to_organisation_nonexistent_organisation(admin_request, sample_service, fake_uuid):
    data = {'service_id': str(sample_service().id)}

    admin_request.post(
        'organisation.link_service_to_organisation', _data=data, organisation_id=fake_uuid, _expected_status=404
    )


def test_post_link_service_to_organisation_nonexistent_service(
    admin_request,
    sample_organisation,
    fake_uuid,
):
    data = {'service_id': fake_uuid}

    admin_request.post(
        'organisation.link_service_to_organisation',
        _data=data,
        organisation_id=str(sample_organisation().id),
        _expected_status=404,
    )


def test_post_link_service_to_organisation_missing_payload(
    admin_request,
    sample_organisation,
    fake_uuid,
):
    admin_request.post(
        'organisation.link_service_to_organisation', organisation_id=str(sample_organisation().id), _expected_status=400
    )


def test_rest_get_organisation_services(
    admin_request,
    sample_organisation,
    sample_service,
):
    org = sample_organisation()
    service = sample_service()
    dao_add_service_to_organisation(service, org.id)
    response = admin_request.get(
        'organisation.get_organisation_services', organisation_id=str(org.id), _expected_status=200
    )

    assert response == [service.serialize_for_org_dashboard()]


def test_add_user_to_organisation_returns_added_user(
    admin_request,
    sample_organisation,
    sample_user,
):
    org = sample_organisation()
    user = sample_user()
    response = admin_request.post(
        'organisation.add_user_to_organisation', organisation_id=str(org.id), user_id=str(user.id), _expected_status=200
    )

    assert response['data']['id'] == str(user.id)
    assert len(response['data']['organisations']) == 1
    assert response['data']['organisations'][0] == str(org.id)


def test_add_user_to_organisation_returns_404_if_user_does_not_exist(admin_request, sample_organisation):
    admin_request.post(
        'organisation.add_user_to_organisation',
        organisation_id=str(sample_organisation().id),
        user_id=str(uuid.uuid4()),
        _expected_status=404,
    )


def test_get_organisation_users_returns_users_for_organisation(
    admin_request,
    sample_organisation,
    sample_user,
):
    first = sample_user()
    second = sample_user()
    org = sample_organisation()
    dao_add_user_to_organisation(organisation_id=org.id, user_id=first.id)
    dao_add_user_to_organisation(organisation_id=org.id, user_id=second.id)

    response = admin_request.get('organisation.get_organisation_users', organisation_id=org.id, _expected_status=200)

    assert len(response['data']) == 2
    assert response['data'][0]['id'] == str(first.id)


def test_is_organisation_name_unique_returns_200_if_unique(
    admin_request,
    sample_organisation,
):
    organisation = sample_organisation(name='unique')

    response = admin_request.get(
        'organisation.is_organisation_name_unique', _expected_status=200, org_id=organisation.id, name='something'
    )

    assert response == {'result': True}


def test_is_organisation_name_unique_returns_200_and_false_if_name_exists_for_a_different_organisation(
    admin_request,
    sample_organisation,
):
    sample_organisation(name='existing name')
    different_organisation_id = '111aa111-2222-bbbb-aaaa-111111111111'

    response = admin_request.get(
        'organisation.is_organisation_name_unique',
        _expected_status=200,
        org_id=different_organisation_id,
        name='existing name',
    )

    assert response == {'result': False}


def test_is_organisation_name_unique_returns_400_when_name_does_not_exist(admin_request):
    response = admin_request.get('organisation.is_organisation_name_unique', _expected_status=400)

    assert response['message'][0]['org_id'] == ["Can't be empty"]
    assert response['message'][1]['name'] == ["Can't be empty"]
