import uuid

from tests import create_admin_authorization_header


def test_archive_only_allows_post(client):
    auth_header = create_admin_authorization_header()
    response = client.get('/service/{}/archive'.format(uuid.uuid4()), headers=[auth_header])
    assert response.status_code == 405
