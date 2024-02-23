import pytest
from sqlalchemy import select

from app.models import INVITE_PENDING, Notification
from tests.app.db import create_invited_org_user


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
@pytest.mark.parametrize(
    'extra_args, expected_start_of_invite_url',
    [
        ({}, 'http://localhost:6012/organisation-invitation/'),
        ({'invite_link_host': 'https://www.example.com'}, 'https://www.example.com/organisation-invitation/'),
    ],
)
def test_create_invited_org_user(
    notify_db_session,
    admin_request,
    sample_organisation,
    sample_user,
    mocker,
    # org_invite_email_template,
    extra_args,
    expected_start_of_invite_url,
):
    mocked = mocker.patch('app.celery.provider_tasks.deliver_email.apply_async')

    org = sample_organisation()
    user = sample_user()
    email_address = 'invited_user@example.com'

    data = dict(organisation=str(org.id), email_address=email_address, invited_by=str(user.id), **extra_args)

    json_resp = admin_request.post(
        'organisation_invite.invite_user_to_org',
        organisation_id=org.id,
        _data=data,
        _expected_status=201,
    )

    assert json_resp['data']['organisation'] == str(org.id)
    assert json_resp['data']['email_address'] == email_address
    assert json_resp['data']['invited_by'] == str(user.id)
    assert json_resp['data']['status'] == INVITE_PENDING
    assert json_resp['data']['id']

    stmt = select(Notification)
    notification = notify_db_session.session.scalars(stmt).first()

    assert notification.reply_to_text == user.email_address

    assert len(notification.personalisation.keys()) == 3
    assert notification.personalisation['organisation_name'] == 'sample organisation'
    assert notification.personalisation['user_name'] == 'Test User'
    assert notification.personalisation['url'].startswith(expected_start_of_invite_url)
    assert len(notification.personalisation['url']) > len(expected_start_of_invite_url)

    result_notification_id, result_queue = mocked.call_args
    result_id, *rest = result_notification_id[0]
    assert result_id == str(notification.id)

    assert result_queue['queue'] == 'notify-internal-tasks'
    mocked.assert_called_once()


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


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_get_all_invited_users_by_service(admin_request, sample_organisation, sample_user):
    org = sample_organisation()
    user = sample_user()

    for i in range(5):
        create_invited_org_user(org, user, email_address='invited_user_{}@service.va.gov'.format(i))

    json_resp = admin_request.get('organisation_invite.get_invited_org_users_by_organisation', organisation_id=org.id)

    assert len(json_resp['data']) == 5
    for invite in json_resp['data']:
        assert invite['organisation'] == str(org.id)
        assert invite['invited_by'] == str(user.id)
        assert invite['id']


def test_get_invited_users_by_service_with_no_invites(admin_request, sample_organisation):
    json_resp = admin_request.get(
        'organisation_invite.get_invited_org_users_by_organisation', organisation_id=sample_organisation().id
    )
    assert len(json_resp['data']) == 0


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_update_org_invited_user_set_status_to_cancelled(admin_request, sample_invited_org_user):
    data = {'status': 'cancelled'}

    json_resp = admin_request.post(
        'organisation_invite.update_org_invite_status',
        organisation_id=sample_invited_org_user.organisation_id,
        invited_org_user_id=sample_invited_org_user.id,
        _data=data,
    )
    assert json_resp['data']['status'] == 'cancelled'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_update_org_invited_user_for_wrong_service_returns_404(admin_request, sample_invited_org_user, fake_uuid):
    data = {'status': 'cancelled'}

    json_resp = admin_request.post(
        'organisation_invite.update_org_invite_status',
        organisation_id=fake_uuid,
        invited_org_user_id=sample_invited_org_user.id,
        _data=data,
        _expected_status=404,
    )
    assert json_resp['message'] == 'No result found'


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_update_org_invited_user_for_invalid_data_returns_400(admin_request, sample_invited_org_user):
    data = {'status': 'garbage'}

    json_resp = admin_request.post(
        'organisation_invite.update_org_invite_status',
        organisation_id=sample_invited_org_user.organisation_id,
        invited_org_user_id=sample_invited_org_user.id,
        _data=data,
        _expected_status=400,
    )
    assert len(json_resp['errors']) == 1
    assert json_resp['errors'][0]['message'] == 'status garbage is not one of [pending, accepted, cancelled]'
