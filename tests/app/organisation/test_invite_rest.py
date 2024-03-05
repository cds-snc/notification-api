def test_create_invited_user_invalid_email(admin_request, sample_organisation, sample_user, mocker):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    org = sample_organisation()
    email_address = 'notanemail'

    data = {
        'service': str(org.id),
        'email_address': email_address,
        'invited_by': str(sample_user().id),
    }

    json_resp = admin_request.post(
        'organisation_invite.invite_user_to_org',
        organisation_id=org.id,
        _data=data,
        _expected_status=400,
    )

    assert json_resp['errors'][0]['message'] == 'email_address Not a valid email address'
    assert mocked.call_count == 0


def test_get_invited_users_by_service_with_no_invites(admin_request, sample_organisation):
    json_resp = admin_request.get(
        'organisation_invite.get_invited_org_users_by_organisation', organisation_id=sample_organisation().id
    )
    assert len(json_resp['data']) == 0
