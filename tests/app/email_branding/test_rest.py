from sqlalchemy import delete

from app.constants import BRANDING_ORG
from app.models import EmailBranding


def test_get_email_branding_options(
    admin_request,
    sample_email_branding,
):
    email_branding1 = sample_email_branding(colour='#FFFFFF', logo='/path/image.png', name='Org1')
    email_branding2 = sample_email_branding(colour='#000000', logo='/path/other.png', name='Org2')
    test_brandings = (str(email_branding1.id), str(email_branding2.id))

    email_branding = admin_request.get('email_branding.get_email_branding_options')['email_branding']

    assert len(email_branding) == 2

    for branding in email_branding:
        assert branding['id'] in test_brandings


def test_get_email_branding_by_id(
    admin_request,
    sample_email_branding,
):
    email_branding = sample_email_branding(colour='#FFFFFF', logo='/path/image.png', name='Some Org', text='My Org')

    response = admin_request.get(
        'email_branding.get_email_branding_by_id', _expected_status=200, email_branding_id=email_branding.id
    )

    assert set(response['email_branding'].keys()) == {'colour', 'logo', 'name', 'id', 'text', 'brand_type'}
    assert response['email_branding']['colour'] == '#FFFFFF'
    assert response['email_branding']['logo'] == '/path/image.png'
    assert response['email_branding']['name'] == 'Some Org'
    assert response['email_branding']['text'] == 'My Org'
    assert response['email_branding']['id'] == str(email_branding.id)
    assert response['email_branding']['brand_type'] == str(email_branding.brand_type)


def test_post_create_email_branding(
    admin_request,
    notify_db_session,
):
    data = {
        'name': 'test email_branding',
        'colour': '#0000ff',
        'logo': '/images/test_x2.png',
        'brand_type': BRANDING_ORG,
    }
    response = admin_request.post('email_branding.create_email_branding', _data=data, _expected_status=201)

    try:
        assert data['name'] == response['data']['name']
        assert data['colour'] == response['data']['colour']
        assert data['logo'] == response['data']['logo']
        assert data['name'] == response['data']['text']
        assert data['brand_type'] == response['data']['brand_type']
    finally:
        # Teardown
        stmt = delete(EmailBranding).where(EmailBranding.id == response['data']['id'])
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


def test_post_create_email_branding_colour_is_valid(
    admin_request,
    notify_db_session,
):
    data = {'logo': 'images/text_x2.png', 'name': 'test branding'}
    response = admin_request.post('email_branding.create_email_branding', _data=data, _expected_status=201)

    try:
        assert response['data']['logo'] == data['logo']
        assert response['data']['name'] == 'test branding'
        assert response['data']['colour'] is None
        assert response['data']['text'] == 'test branding'
    finally:
        # Teardown
        stmt = delete(EmailBranding).where(EmailBranding.id == response['data']['id'])
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


def test_post_create_email_branding_with_text_and_name(
    admin_request,
    notify_db_session,
):
    data = {'name': 'name for brand', 'text': 'text for brand', 'logo': 'images/text_x2.png'}
    response = admin_request.post('email_branding.create_email_branding', _data=data, _expected_status=201)

    try:
        assert response['data']['logo'] == data['logo']
        assert response['data']['name'] == 'name for brand'
        assert response['data']['colour'] is None
        assert response['data']['text'] == 'text for brand'
        assert response['data']['id']
    finally:
        # Teardown
        stmt = delete(EmailBranding).where(EmailBranding.id == response['data']['id'])
        notify_db_session.session.execute(stmt)
        notify_db_session.session.commit()


def test_post_create_email_branding_returns_400_when_name_is_missing(
    admin_request,
):
    data = {'text': 'some text', 'logo': 'images/text_x2.png'}
    response = admin_request.post('email_branding.create_email_branding', _data=data, _expected_status=400)

    assert response['errors'][0]['message'] == 'name is a required property'


def test_create_email_branding_reject_invalid_brand_type(
    admin_request,
):
    data = {'name': 'test email_branding', 'brand_type': 'NOT A TYPE'}
    response = admin_request.post('email_branding.create_email_branding', _data=data, _expected_status=400)

    expect = 'brand_type NOT A TYPE is not one of (org, both, org_banner, no_branding)'
    assert response['errors'][0]['message'] == expect
