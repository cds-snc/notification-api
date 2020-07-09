from app import db
from app.dao.dao_utils import transactional


@transactional
def dao_create_organisation_type(organisation_type):
    db.session.add(organisation_type)
