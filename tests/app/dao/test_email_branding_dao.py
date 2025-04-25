from uuid import uuid4

from app.dao.email_branding_dao import dao_get_email_branding_by_name
from app.models import EmailBranding


def test_get_email_branding_by_name_gets_correct_email_branding(sample_email_branding):
    email_branding_name = str(uuid4())
    email_branding = sample_email_branding(name=email_branding_name)

    email_branding_from_db = dao_get_email_branding_by_name(email_branding_name)

    assert email_branding_from_db == email_branding


def test_email_branding_has_no_domain(notify_db_session, sample_email_branding):
    branding = sample_email_branding(name=str(uuid4()))

    email_branding: EmailBranding = notify_db_session.session.get(EmailBranding, branding.id)
    assert not hasattr(email_branding, 'domain')
