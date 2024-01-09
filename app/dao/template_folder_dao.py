from app import db
from app.dao.dao_utils import transactional
from app.models import TemplateFolder
from sqlalchemy import select


def dao_get_template_folder_by_id_and_service_id(
    template_folder_id,
    service_id,
):
    stmt = select(TemplateFolder).where(
        TemplateFolder.id == template_folder_id, TemplateFolder.service_id == service_id
    )

    return db.session.scalars(stmt).one()


def dao_get_valid_template_folders_by_id(folder_ids):
    stmt = select(TemplateFolder).where(TemplateFolder.id.in_(folder_ids))
    return db.session.scalars(stmt).all()


@transactional
def dao_create_template_folder(template_folder):
    db.session.add(template_folder)


@transactional
def dao_update_template_folder(template_folder):
    db.session.add(template_folder)


@transactional
def dao_delete_template_folder(template_folder):
    db.session.delete(template_folder)
