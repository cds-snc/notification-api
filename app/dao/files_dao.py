from datetime import datetime, timezone

from app import db
from app.dao.dao_utils import transactional
from app.models import FILE_STATUS_UPLOADED, FILE_TYPE_TEMPLATE_ATTACH, Files


def dao_get_files_by_template_id(template_id):
    return Files.query.filter(
        Files.template_id == template_id,
    ).all()


def dao_get_template_attachments(template_id):
    """Get all uploaded template attachments for a template.

    Returns:
        List of Files objects with type='template_attach' and status='uploaded'
    """
    return Files.query.filter(
        Files.template_id == template_id,
        Files.type == FILE_TYPE_TEMPLATE_ATTACH,
        Files.status == FILE_STATUS_UPLOADED,
    ).all()


def dao_get_file_status_by_id_and_template_id(file_id, template_id):
    return db.session.query(Files.status).filter(Files.id == file_id, Files.template_id == template_id).scalar()


def dao_get_file_by_id(file_id):
    return Files.query.filter(Files.id == file_id).one()


def dao_get_file_by_document_id(document_id):
    return Files.query.filter(Files.document_id == document_id).one()


@transactional
def dao_create_file(file):
    db.session.add(file)
    return file


@transactional
def dao_update_file(file: Files):
    file.updated_at = datetime.now(timezone.utc)
    db.session.add(file)
    return file


@transactional
def dao_delete_file(file):
    db.session.delete(file)
