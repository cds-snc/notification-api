import pytest
import uuid
from flask import current_app
from freezegun import freeze_time
from notifications_utils.url_safe_token import generate_token
from tests import create_admin_authorization_header


@pytest.mark.parametrize('invitation_type', ['service', 'organisation'])
def test_validate_invitation_token_for_expired_token_returns_400(client, invitation_type):
    with freeze_time('2016-01-01T12:00:00'):
        token = generate_token(
            str(uuid.uuid4()), current_app.config['SECRET_KEY'], current_app.config['DANGEROUS_SALT']
        )
    url = '/invite/{}/{}'.format(invitation_type, token)
    auth_header = create_admin_authorization_header()
    response = client.get(url, headers=[('Content-Type', 'application/json'), auth_header])

    assert response.status_code == 400
    json_resp = response.get_json()
    assert json_resp['result'] == 'error'
    assert json_resp['message'] == {
        'invitation': [
            'Your invitation to GOV.UK Notify has expired. '
            'Please ask the person that invited you to send you another one'
        ]
    }


@pytest.mark.parametrize('invitation_type', ['service', 'organisation'])
def test_validate_invitation_token_returns_400_when_invited_user_does_not_exist(client, invitation_type):
    token = generate_token(str(uuid.uuid4()), current_app.config['SECRET_KEY'], current_app.config['DANGEROUS_SALT'])
    url = '/invite/{}/{}'.format(invitation_type, token)
    auth_header = create_admin_authorization_header()
    response = client.get(url, headers=[('Content-Type', 'application/json'), auth_header])

    assert response.status_code == 404
    json_resp = response.get_json()
    assert json_resp['result'] == 'error'
    assert json_resp['message'] == 'No result found'


@pytest.mark.parametrize('invitation_type', ['service', 'organisation'])
def test_validate_invitation_token_returns_400_when_token_is_malformed(client, invitation_type):
    token = generate_token(str(uuid.uuid4()), current_app.config['SECRET_KEY'], current_app.config['DANGEROUS_SALT'])[
        :-2
    ]

    url = '/invite/{}/{}'.format(invitation_type, token)
    auth_header = create_admin_authorization_header()
    response = client.get(url, headers=[('Content-Type', 'application/json'), auth_header])

    assert response.status_code == 400
    json_resp = response.get_json()
    assert json_resp['result'] == 'error'
    assert json_resp['message'] == {
        'invitation': 'Something’s wrong with this link. Make sure you’ve copied the whole thing.'
    }
