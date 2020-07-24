from app import db
from app.models import ServiceSafelist


def dao_fetch_service_safelist(service_id):
    return ServiceSafelist.query.filter(
        ServiceSafelist.service_id == service_id).all()


def dao_add_and_commit_safelisted_contacts(objs):
    db.session.add_all(objs)
    db.session.commit()


def dao_remove_service_safelist(service_id):
    return ServiceSafelist.query.filter(
        ServiceSafelist.service_id == service_id).delete()
