from app.dao.files_dao import (
    dao_create_file,
    dao_get_template_attachments,
)
from app.models import FILE_STATUS_PENDING_VIRUS_SCAN, FILE_STATUS_UPLOADED, FILE_TYPE_ATTACH, FILE_TYPE_TEMPLATE_ATTACH, Files
from tests.app.db import create_template


def test_dao_get_template_attachments_returns_uploaded_template_attachments(sample_service, sample_user):
    """Test that dao_get_template_attachments returns only uploaded template_attach files"""
    template = create_template(sample_service, template_type="email", created_by=sample_user)

    # Create template attachment (uploaded)
    template_attachment = Files(
        template_id=template.id,
        service_id=sample_service.id,
        document_id="doc-1",
        type=FILE_TYPE_TEMPLATE_ATTACH,
        name="terms.pdf",
        mime_type="application/pdf",
        file_size=12345,
        status=FILE_STATUS_UPLOADED,
    )
    dao_create_file(template_attachment)

    # Create another uploaded attachment
    template_attachment_2 = Files(
        template_id=template.id,
        service_id=sample_service.id,
        document_id="doc-2",
        type=FILE_TYPE_TEMPLATE_ATTACH,
        name="policy.pdf",
        mime_type="application/pdf",
        file_size=67890,
        status=FILE_STATUS_UPLOADED,
    )
    dao_create_file(template_attachment_2)

    # Create pending scan attachment (should be excluded)
    pending_attachment = Files(
        template_id=template.id,
        service_id=sample_service.id,
        document_id="doc-3",
        type=FILE_TYPE_TEMPLATE_ATTACH,
        name="pending.pdf",
        mime_type="application/pdf",
        file_size=11111,
        status=FILE_STATUS_PENDING_VIRUS_SCAN,
    )
    dao_create_file(pending_attachment)

    # Create non-template attachment (should be excluded)
    other_attachment = Files(
        template_id=template.id,
        service_id=sample_service.id,
        document_id="doc-4",
        type=FILE_TYPE_ATTACH,
        name="other.pdf",
        mime_type="application/pdf",
        file_size=22222,
        status=FILE_STATUS_UPLOADED,
    )
    dao_create_file(other_attachment)

    # Get template attachments
    attachments = dao_get_template_attachments(template.id)

    # Should only return the 2 uploaded template_attach files
    assert len(attachments) == 2
    assert all(a.type == FILE_TYPE_TEMPLATE_ATTACH for a in attachments)
    assert all(a.status == FILE_STATUS_UPLOADED for a in attachments)
    assert {a.name for a in attachments} == {"terms.pdf", "policy.pdf"}


def test_dao_get_template_attachments_returns_empty_list_when_no_attachments(sample_service, sample_user):
    """Test that dao_get_template_attachments returns empty list when no attachments exist"""
    template = create_template(sample_service, template_type="email", created_by=sample_user)

    attachments = dao_get_template_attachments(template.id)

    assert attachments == []


def test_dao_get_template_attachments_filters_by_template_id(sample_service, sample_user):
    """Test that dao_get_template_attachments only returns attachments for specified template"""
    template_1 = create_template(sample_service, template_type="email", created_by=sample_user, template_name="Template 1")
    template_2 = create_template(sample_service, template_type="email", created_by=sample_user, template_name="Template 2")

    # Create attachment for template 1
    attachment_1 = Files(
        template_id=template_1.id,
        service_id=sample_service.id,
        document_id="doc-1",
        type=FILE_TYPE_TEMPLATE_ATTACH,
        name="file1.pdf",
        mime_type="application/pdf",
        file_size=12345,
        status=FILE_STATUS_UPLOADED,
    )
    dao_create_file(attachment_1)

    # Create attachment for template 2
    attachment_2 = Files(
        template_id=template_2.id,
        service_id=sample_service.id,
        document_id="doc-2",
        type=FILE_TYPE_TEMPLATE_ATTACH,
        name="file2.pdf",
        mime_type="application/pdf",
        file_size=67890,
        status=FILE_STATUS_UPLOADED,
    )
    dao_create_file(attachment_2)

    # Get attachments for template 1
    attachments = dao_get_template_attachments(template_1.id)

    # Should only return attachment for template 1
    assert len(attachments) == 1
    assert attachments[0].name == "file1.pdf"
    assert attachments[0].template_id == template_1.id
