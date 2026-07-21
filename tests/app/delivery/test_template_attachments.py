"""
Tests for template file attachment functionality in send_to_providers.py

Tests cover:
- Fetching template files from cache or database
- Downloading files from document-download-api
- Merging payload and template attachments
- Enforcing attachment limits
- Integration with send_email_to_provider for all send paths
"""

import json
import uuid
from unittest.mock import MagicMock

import pytest

from app.delivery import send_to_providers
from app.models import FILE_STATUS_UPLOADED, FILE_TYPE_TEMPLATE_ATTACH
from tests.app.conftest import create_sample_email_template, create_sample_job
from tests.app.db import (
    create_notification,
    save_notification,
)


@pytest.fixture
def sample_template_with_files(notify_db, notify_db_session, sample_service_full_permissions):
    """Create an email template for testing."""
    return create_sample_email_template(
        notify_db,
        notify_db_session,
        service=sample_service_full_permissions,
    )


@pytest.fixture
def sample_template_files(notify_db, notify_db_session, sample_service_full_permissions, sample_template_with_files):
    """Create test files for a template."""
    from app.dao.files_dao import dao_create_file
    from app.models import Files

    files = []
    for i in range(3):
        file = Files(
            template_id=sample_template_with_files.id,
            service_id=sample_service_full_permissions.id,
            document_id=uuid.uuid4(),
            type=FILE_TYPE_TEMPLATE_ATTACH,
            name=f"test_file_{i}.pdf",
            status=FILE_STATUS_UPLOADED,
            mime_type="application/pdf",
        )
        created_file = dao_create_file(file)
        files.append(created_file)
    return files


class TestGetTemplateFilesFromCacheOrDb:
    """Test _get_template_files_from_cache_or_db helper function."""

    def test_returns_empty_list_when_no_files_exist(self, sample_email_template):
        """Test that empty list is returned when template has no files."""
        result = send_to_providers._get_template_files_from_cache_or_db(
            job_id=None,
            template_id=sample_email_template.id,
        )
        assert result == []

    def test_fetches_from_db_when_no_job_id(self, sample_template_with_files, sample_template_files):
        """Test that files are fetched from DB for one-off sends (no job_id)."""
        result = send_to_providers._get_template_files_from_cache_or_db(
            job_id=None,
            template_id=sample_template_with_files.id,
        )

        assert len(result) == 3
        assert all("name" in f and "document_id" in f for f in result)
        assert result[0]["name"] == "test_file_0.pdf"

    def test_caches_on_miss_for_bulk_job(self, sample_template_with_files, sample_template_files, mocker):
        """Test that files are cached on retrieval miss for bulk jobs (as safety fallback)."""
        job_id = uuid.uuid4()
        redis_mock = mocker.patch("app.delivery.send_to_providers.redis_store")
        redis_mock.get.return_value = None  # Cache miss

        result = send_to_providers._get_template_files_from_cache_or_db(
            job_id=job_id,
            template_id=sample_template_with_files.id,
        )

        # Should have fetched files from DB
        assert len(result) == 3

        # Should have cached on miss (safety fallback if pre-cache from tasks layer expires)
        redis_mock.set.assert_called_once()
        call_args = redis_mock.set.call_args
        cache_key = call_args[0][0]
        cached_value = call_args[0][1]

        assert cache_key == f"template_files:{job_id}"
        # Verify it's valid JSON and contains 3 files
        cached_files = json.loads(cached_value)
        assert len(cached_files) == 3
        assert all("name" in f and "document_id" in f for f in cached_files)
        assert call_args[1]["ex"] == 86400

    def test_caches_empty_list_on_miss_for_bulk_job(self, sample_email_template, mocker):
        """Test that empty list is cached on retrieval miss for bulk jobs (prevents repeated DB hits for no-attachment templates)."""
        job_id = uuid.uuid4()
        redis_mock = mocker.patch("app.delivery.send_to_providers.redis_store")
        redis_mock.get.return_value = None  # Cache miss

        result = send_to_providers._get_template_files_from_cache_or_db(
            job_id=job_id,
            template_id=sample_email_template.id,
        )

        # Should return empty list
        assert result == []

        # Should have cached empty list (not skipped because it's empty)
        redis_mock.set.assert_called_once()
        call_args = redis_mock.set.call_args
        cache_key = call_args[0][0]
        cached_value = call_args[0][1]

        assert cache_key == f"template_files:{job_id}"
        assert cached_value == json.dumps([])
        assert call_args[1]["ex"] == 86400

    def test_retrieves_from_cache_on_hit(self, sample_template_with_files, mocker):
        """Test that cached files are retrieved on cache hit."""
        job_id = uuid.uuid4()
        cache_key = f"template_files:{job_id}"

        cached_files = [
            {"name": "cached_1.pdf", "document_id": "doc-123", "mime_type": "application/pdf", "service_id": "svc-123"},
            {"name": "cached_2.pdf", "document_id": "doc-456", "mime_type": "application/pdf", "service_id": "svc-123"},
        ]

        redis_mock = mocker.patch("app.delivery.send_to_providers.redis_store")
        redis_mock.get.return_value = json.dumps(cached_files)

        result = send_to_providers._get_template_files_from_cache_or_db(
            job_id=job_id,
            template_id=sample_template_with_files.id,
        )

        # Should return cached files
        assert result == cached_files
        redis_mock.get.assert_called_once_with(cache_key)

    def test_falls_back_to_db_on_cache_failure(self, sample_template_with_files, sample_template_files, mocker):
        """Test fallback to DB when Redis cache fails."""
        job_id = uuid.uuid4()

        redis_mock = mocker.patch("app.delivery.send_to_providers.redis_store")
        redis_mock.get.side_effect = Exception("Redis connection failed")

        result = send_to_providers._get_template_files_from_cache_or_db(
            job_id=job_id,
            template_id=sample_template_with_files.id,
        )

        # Should still return files from DB
        assert len(result) == 3


class TestDownloadTemplateFile:
    """Test _download_template_file helper function."""

    def test_downloads_file_successfully(self, notify_api, mocker):
        """Test successful file download from document-download-api."""
        service_id = uuid.uuid4()
        document_id = "doc-123"
        filename = "test.pdf"
        mime_type = "application/pdf"

        # Mock document_download_client.check_scan_verdict
        mocker.patch("app.delivery.send_to_providers.document_download_client.check_scan_verdict")
        mocker.patch("app.delivery.send_to_providers.check_for_malware_errors")

        # Mock HTTP download
        http_mock = MagicMock()
        http_mock.request.return_value.status = 200
        http_mock.request.return_value.data = b"file_content"

        mocker.patch("app.delivery.send_to_providers.PoolManager", return_value=http_mock)

        result = send_to_providers._download_template_file(
            service_id=service_id,
            document_id=document_id,
            filename=filename,
            mime_type=mime_type,
        )

        assert result is not None
        assert result["name"] == filename
        assert result["data"] == b"file_content"
        assert result["mime_type"] == mime_type

    def test_returns_none_on_download_failure(self, notify_api, mocker):
        """Test that None is returned on HTTP download failure."""
        service_id = uuid.uuid4()
        document_id = "doc-123"

        mocker.patch("app.delivery.send_to_providers.document_download_client.check_scan_verdict")
        mocker.patch("app.delivery.send_to_providers.check_for_malware_errors")

        # Mock HTTP failure
        http_mock = MagicMock()
        http_mock.request.return_value.status = 404

        mocker.patch("app.delivery.send_to_providers.PoolManager", return_value=http_mock)

        result = send_to_providers._download_template_file(
            service_id=service_id,
            document_id=document_id,
            filename="test.pdf",
            mime_type="application/pdf",
        )

        assert result is None

    def test_returns_none_on_exception(self, notify_api, mocker):
        """Test that None is returned on exception during download."""
        service_id = uuid.uuid4()
        document_id = "doc-123"

        mocker.patch("app.delivery.send_to_providers.document_download_client.check_scan_verdict")
        mocker.patch("app.delivery.send_to_providers.check_for_malware_errors")

        # Mock exception
        mocker.patch("app.delivery.send_to_providers.PoolManager", side_effect=Exception("Connection error"))

        result = send_to_providers._download_template_file(
            service_id=service_id,
            document_id=document_id,
            filename="test.pdf",
            mime_type="application/pdf",
        )

        assert result is None


class TestGetTemplateAttachments:
    """Test _get_template_attachments helper function."""

    def test_returns_empty_list_when_no_template_files(self, sample_service, sample_email_template, mocker):
        """Test that empty list is returned when template has no files."""
        notification = save_notification(
            create_notification(
                template=sample_email_template,
                to_field="test@example.com",
            )
        )

        mocker.patch(
            "app.delivery.send_to_providers._get_template_files_from_cache_or_db",
            return_value=[],
        )

        attachments, metadata = send_to_providers._get_template_attachments(notification)
        assert attachments == []
        assert metadata == []

    def test_downloads_all_template_files(self, sample_service, sample_email_template, mocker):
        """Test that all template files are downloaded."""
        notification = save_notification(
            create_notification(
                template=sample_email_template,
                to_field="test@example.com",
            )
        )

        file_metadata = [
            {"name": "file1.pdf", "document_id": "doc-1", "mime_type": "application/pdf", "service_id": str(sample_service.id)},
            {"name": "file2.pdf", "document_id": "doc-2", "mime_type": "application/pdf", "service_id": str(sample_service.id)},
        ]

        mocker.patch(
            "app.delivery.send_to_providers._get_template_files_from_cache_or_db",
            return_value=file_metadata,
        )

        download_mock = mocker.patch("app.delivery.send_to_providers._download_template_file")
        download_mock.side_effect = [
            {"name": "file1.pdf", "data": b"content1", "mime_type": "application/pdf"},
            {"name": "file2.pdf", "data": b"content2", "mime_type": "application/pdf"},
        ]

        attachments, metadata = send_to_providers._get_template_attachments(notification)

        assert len(attachments) == 2
        assert attachments[0]["name"] == "file1.pdf"
        assert attachments[1]["name"] == "file2.pdf"
        assert len(metadata) == 2
        assert metadata[0]["document_id"] == "doc-1"
        assert metadata[1]["document_id"] == "doc-2"

    def test_skips_files_that_fail_to_download(self, sample_service, sample_email_template, mocker):
        """Test that failed downloads are skipped."""
        notification = save_notification(
            create_notification(
                template=sample_email_template,
                to_field="test@example.com",
            )
        )

        file_metadata = [
            {
                "name": "file1.pdf",
                "document_id": "doc-1",
                "mime_type": "application/pdf",
                "service_id": str(sample_service.id),
                "file_id": "f1",
            },
            {
                "name": "file2.pdf",
                "document_id": "doc-2",
                "mime_type": "application/pdf",
                "service_id": str(sample_service.id),
                "file_id": "f2",
            },
        ]

        mocker.patch(
            "app.delivery.send_to_providers._get_template_files_from_cache_or_db",
            return_value=file_metadata,
        )

        download_mock = mocker.patch("app.delivery.send_to_providers._download_template_file")
        download_mock.side_effect = [
            {"name": "file1.pdf", "data": b"content1", "mime_type": "application/pdf"},
            None,  # Second file fails
        ]

        attachments, metadata = send_to_providers._get_template_attachments(notification)

        # Should only return the successful download and its metadata
        assert len(attachments) == 1
        assert attachments[0]["name"] == "file1.pdf"
        assert len(metadata) == 1
        assert metadata[0]["document_id"] == "doc-1"


class TestSendEmailToProviderWithTemplateAttachments:
    """Test send_email_to_provider with template attachments."""

    def test_includes_template_attachments_for_one_off_send(self, sample_service, sample_email_template, mocker):
        """Test that template attachments are included in one-off email sends."""
        notification = save_notification(
            create_notification(
                template=sample_email_template,
                to_field="test@example.com",
            )
        )

        # Mock template attachments
        template_attachments = [
            {"name": "template.pdf", "data": b"template_content", "mime_type": "application/pdf"},
        ]

        mocker.patch("app.delivery.send_to_providers._get_template_attachments", return_value=(template_attachments, []))
        mocker.patch("app.delivery.send_to_providers.provider_to_use")
        mocker.patch("app.delivery.send_to_providers.dao_get_template_by_id")
        mocker.patch("app.delivery.send_to_providers.is_service_allowed_html", return_value=False)
        mocker.patch("app.delivery.send_to_providers.get_html_email_options", return_value={})
        mocker.patch("app.delivery.send_to_providers.HTMLEmailTemplate")
        mocker.patch("app.delivery.send_to_providers.PlainTextEmailTemplate")
        mocker.patch("app.delivery.send_to_providers.send_email_response", return_value="ref-123")

        provider_mock = MagicMock()
        provider_mock.send_email.return_value = "ses-ref"
        provider_mock.get_name.return_value = "ses"

        mocker.patch("app.delivery.send_to_providers.provider_to_use", return_value=provider_mock)

        send_to_providers.send_email_to_provider(notification)

        # Verify provider.send_email was called with attachments
        provider_mock.send_email.assert_called_once()
        call_kwargs = provider_mock.send_email.call_args[1]
        assert "attachments" in call_kwargs
        # Should have template attachment
        assert len(call_kwargs["attachments"]) > 0

    def test_merges_payload_and_template_attachments_in_send(self, sample_service, sample_email_template, mocker):
        """Test that payload and template attachments are merged in send."""
        notification = save_notification(
            create_notification(
                template=sample_email_template,
                to_field="test@example.com",
                personalisation={
                    "document": {
                        "document": {
                            "sending_method": "attach",
                            "direct_file_url": "http://example.com/payload.pdf",
                            "filename": "payload.pdf",
                            "mime_type": "application/pdf",
                            "id": "payload-doc-123",
                        }
                    }
                },
            )
        )

        # Mock for payload file download
        template_attachments = [
            {"name": "template.pdf", "data": b"template_content", "mime_type": "application/pdf"},
        ]

        mocker.patch("app.delivery.send_to_providers.document_download_client.check_scan_verdict")
        mocker.patch("app.delivery.send_to_providers.check_for_malware_errors")

        http_mock = MagicMock()
        http_mock.request.return_value.data = b"payload_content"
        mocker.patch("app.delivery.send_to_providers.PoolManager", return_value=http_mock)

        mocker.patch("app.delivery.send_to_providers._get_template_attachments", return_value=(template_attachments, []))
        mocker.patch("app.delivery.send_to_providers.provider_to_use")
        mocker.patch("app.delivery.send_to_providers.dao_get_template_by_id")
        mocker.patch("app.delivery.send_to_providers.is_service_allowed_html", return_value=False)
        mocker.patch("app.delivery.send_to_providers.get_html_email_options", return_value={})
        mocker.patch("app.delivery.send_to_providers.HTMLEmailTemplate")
        mocker.patch("app.delivery.send_to_providers.PlainTextEmailTemplate")
        mocker.patch("app.delivery.send_to_providers.send_email_response", return_value="ref-123")

        provider_mock = MagicMock()
        provider_mock.send_email.return_value = "ses-ref"
        provider_mock.get_name.return_value = "ses"

        mocker.patch("app.delivery.send_to_providers.provider_to_use", return_value=provider_mock)

        send_to_providers.send_email_to_provider(notification)

        # Verify both payload and template attachments are sent
        provider_mock.send_email.assert_called_once()
        call_kwargs = provider_mock.send_email.call_args[1]
        attachments = call_kwargs["attachments"]
        assert len(attachments) == 2
        assert attachments[0]["name"] == "payload.pdf"
        assert attachments[1]["name"] == "template.pdf"

    def test_skips_template_attach_entries_from_personalisation(self, sample_service, sample_email_template, mocker):
        """Test that template_attach entries in personalisation data are skipped from file processing.

        This ensures that when admin adds template attachments to personalisation data for audit logging,
        they don't get caught by the user-file processing loop (which expects 'url' or 'direct_file_url').
        """
        notification = save_notification(
            create_notification(
                template=sample_email_template,
                to_field="test@example.com",
                personalisation={
                    "_file_0": {
                        "document": {
                            "sending_method": "template_attach",
                            "id": "template-attachment-id",
                            "filename": "template-file.pdf",
                            "mime_type": "application/pdf",
                            "file_size": 1024,
                        }
                    }
                },
            )
        )

        template_attachments = [
            {"name": "template-file.pdf", "data": b"template_content", "mime_type": "application/pdf"},
        ]

        mocker.patch("app.delivery.send_to_providers._get_template_attachments", return_value=(template_attachments, []))
        mocker.patch("app.delivery.send_to_providers.provider_to_use")
        mocker.patch("app.delivery.send_to_providers.dao_get_template_by_id")
        mocker.patch("app.delivery.send_to_providers.is_service_allowed_html", return_value=False)
        mocker.patch("app.delivery.send_to_providers.get_html_email_options", return_value={})
        mocker.patch("app.delivery.send_to_providers.HTMLEmailTemplate")
        mocker.patch("app.delivery.send_to_providers.PlainTextEmailTemplate")
        mocker.patch("app.delivery.send_to_providers.send_email_response", return_value="ref-123")

        # Mock document_download_client - should NOT be called for template_attach entries
        document_download_client_mock = mocker.patch("app.delivery.send_to_providers.document_download_client.check_scan_verdict")

        provider_mock = MagicMock()
        provider_mock.send_email.return_value = "ses-ref"
        provider_mock.get_name.return_value = "ses"

        mocker.patch("app.delivery.send_to_providers.provider_to_use", return_value=provider_mock)

        send_to_providers.send_email_to_provider(notification)

        # Verify that check_scan_verdict was NOT called (meaning template_attach was skipped)
        document_download_client_mock.assert_not_called()

        # Verify that the template attachment from _get_template_attachments is still included
        provider_mock.send_email.assert_called_once()
        call_kwargs = provider_mock.send_email.call_args[1]
        attachments = call_kwargs["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["name"] == "template-file.pdf"


class TestAllSendPathsIncludeTemplateAttachments:
    """Test that all 4 send paths (api one-off, api bulk, admin one-off, admin bulk) include template attachments."""

    def _setup_send_email_mocks(self, mocker):
        """Helper to set up common mocks for send_email_to_provider tests."""
        mocker.patch("app.delivery.send_to_providers.provider_to_use")
        mocker.patch("app.delivery.send_to_providers.dao_get_template_by_id")
        mocker.patch("app.delivery.send_to_providers.is_service_allowed_html", return_value=False)
        mocker.patch("app.delivery.send_to_providers.get_html_email_options", return_value={})
        mocker.patch("app.delivery.send_to_providers.HTMLEmailTemplate")
        mocker.patch("app.delivery.send_to_providers.PlainTextEmailTemplate")
        mocker.patch("app.delivery.send_to_providers.send_email_response", return_value="ref-123")

        provider_mock = MagicMock()
        provider_mock.send_email.return_value = "ses-ref"
        provider_mock.get_name.return_value = "ses"
        mocker.patch("app.delivery.send_to_providers.provider_to_use", return_value=provider_mock)

        return provider_mock

    def test_api_one_off_send_includes_template_attachments(self, sample_service, sample_email_template, mocker):
        """Test that API one-off sends include template attachments (no job_id)."""
        notification = save_notification(
            create_notification(
                template=sample_email_template,
                to_field="test@example.com",
            )
        )

        template_attachments = [
            {"name": "template.pdf", "data": b"template_content", "mime_type": "application/pdf"},
        ]

        mocker.patch("app.delivery.send_to_providers._get_template_attachments", return_value=(template_attachments, []))
        provider_mock = self._setup_send_email_mocks(mocker)

        send_to_providers.send_email_to_provider(notification)

        provider_mock.send_email.assert_called_once()
        call_kwargs = provider_mock.send_email.call_args[1]
        attachments = call_kwargs["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["name"] == "template.pdf"

    def test_api_bulk_send_includes_template_attachments(self, sample_service, sample_email_template, mocker):
        """Test that API bulk sends include template attachments (with job_id, cached files)."""
        job_id = uuid.uuid4()

        notification = create_notification(
            template=sample_email_template,
            to_field="test@example.com",
        )
        notification.job_id = job_id
        save_notification(notification)

        template_attachments = [
            {"name": "template1.pdf", "data": b"content1", "mime_type": "application/pdf"},
            {"name": "template2.pdf", "data": b"content2", "mime_type": "application/pdf"},
        ]

        mocker.patch("app.delivery.send_to_providers._get_template_attachments", return_value=(template_attachments, []))
        provider_mock = self._setup_send_email_mocks(mocker)

        send_to_providers.send_email_to_provider(notification)

        provider_mock.send_email.assert_called_once()
        call_kwargs = provider_mock.send_email.call_args[1]
        attachments = call_kwargs["attachments"]
        assert len(attachments) == 2
        assert attachments[0]["name"] == "template1.pdf"
        assert attachments[1]["name"] == "template2.pdf"

    def test_admin_one_off_send_includes_template_attachments(self, sample_service, sample_email_template, mocker):
        """Test that admin one-off sends from UI include template attachments (no job_id)."""
        notification = save_notification(
            create_notification(
                template=sample_email_template,
                to_field="test@example.com",
            )
        )

        template_attachments = [
            {"name": "attachment.pdf", "data": b"admin_content", "mime_type": "application/pdf"},
        ]

        mocker.patch("app.delivery.send_to_providers._get_template_attachments", return_value=(template_attachments, []))
        provider_mock = self._setup_send_email_mocks(mocker)

        send_to_providers.send_email_to_provider(notification)

        provider_mock.send_email.assert_called_once()
        call_kwargs = provider_mock.send_email.call_args[1]
        attachments = call_kwargs["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["name"] == "attachment.pdf"

    def test_admin_bulk_send_includes_template_attachments(self, sample_service, sample_email_template, mocker):
        """Test that admin bulk CSV sends include template attachments (with job_id, cached files)."""
        job_id = uuid.uuid4()

        notification = create_notification(
            template=sample_email_template,
            to_field="test@example.com",
        )
        notification.job_id = job_id
        save_notification(notification)

        template_attachments = [
            {"name": "bulk_attach.pdf", "data": b"bulk_content", "mime_type": "application/pdf"},
        ]

        mocker.patch("app.delivery.send_to_providers._get_template_attachments", return_value=(template_attachments, []))
        provider_mock = self._setup_send_email_mocks(mocker)

        send_to_providers.send_email_to_provider(notification)

        provider_mock.send_email.assert_called_once()
        call_kwargs = provider_mock.send_email.call_args[1]
        attachments = call_kwargs["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["name"] == "bulk_attach.pdf"

    def test_bulk_send_with_job_id_includes_attachments(self, sample_service, sample_email_template, mocker):
        """Test that bulk sends (with job_id) include template attachments."""
        job_id = uuid.uuid4()

        notification = create_notification(
            template=sample_email_template,
            to_field="test@example.com",
        )
        notification.job_id = job_id
        save_notification(notification)

        # For bulk sends with job_id, attachments are retrieved and included
        template_attachments = [
            {"name": "bulk_file.pdf", "data": b"bulk_content", "mime_type": "application/pdf"},
        ]

        mocker.patch("app.delivery.send_to_providers._get_template_attachments", return_value=(template_attachments, []))
        provider_mock = self._setup_send_email_mocks(mocker)

        send_to_providers.send_email_to_provider(notification)

        provider_mock.send_email.assert_called_once()
        call_kwargs = provider_mock.send_email.call_args[1]
        attachments = call_kwargs["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["name"] == "bulk_file.pdf"

    def test_one_off_send_fetches_from_db_not_cache(self, sample_service, sample_email_template, mocker):
        """Test that one-off sends (no job_id) fetch directly from DB, not cache."""
        notification = save_notification(
            create_notification(
                template=sample_email_template,
                to_field="test@example.com",
            )
        )

        # Mock Redis to verify it's NOT accessed for one-off sends
        redis_mock = mocker.patch("app.delivery.send_to_providers.redis_store")

        # Mock database fetch
        mocker.patch(
            "app.delivery.send_to_providers.dao_get_ready_files_by_template_id",
            return_value=[],  # Empty DB result for this test
        )

        # Mock download
        download_mock = mocker.patch("app.delivery.send_to_providers._download_template_file")
        download_mock.return_value = {"name": "direct.pdf", "data": b"content", "mime_type": "application/pdf"}

        provider_mock = self._setup_send_email_mocks(mocker)

        send_to_providers.send_email_to_provider(notification)

        # Verify Redis was NOT accessed (no job_id means no cache attempt)
        redis_mock.get.assert_not_called()

        # Verify attachments were still included
        provider_mock.send_email.assert_called_once()
        call_kwargs = provider_mock.send_email.call_args[1]
        attachments = call_kwargs["attachments"]
        assert len(attachments) == 0  # No files in DB for this test


class TestPersistTemplateAttachmentMetadata:
    """Test that template attachment metadata is persisted into notification.personalisation for history display."""

    def test_persists_metadata_for_bulk_send_without_existing_file_keys(
        self, notify_db, notify_db_session, sample_service, sample_email_template, mocker
    ):
        """Bulk sends have no _file_N keys in personalisation — metadata should be written."""
        job = create_sample_job(
            notify_db,
            notify_db_session,
            service=sample_service,
            template=sample_email_template,
        )

        notification = save_notification(
            create_notification(
                template=sample_email_template,
                job=job,
                to_field="test@example.com",
                personalisation={"name": "Jo"},
            )
        )

        file_metadata = [
            {
                "name": "report.pdf",
                "document_id": "doc-1",
                "mime_type": "application/pdf",
                "service_id": str(sample_service.id),
                "file_id": "file-1",
                "file_size": 102400,
            },
            {
                "name": "summary.docx",
                "document_id": "doc-2",
                "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "service_id": str(sample_service.id),
                "file_id": "file-2",
                "file_size": 204800,
            },
        ]

        send_to_providers._persist_template_attachment_metadata(notification, file_metadata)

        assert "_file_0" in notification.personalisation
        assert "_file_1" in notification.personalisation
        assert notification.personalisation["_file_0"]["document"]["id"] == "doc-1"
        assert notification.personalisation["_file_0"]["document"]["filename"] == "report.pdf"
        assert notification.personalisation["_file_0"]["document"]["sending_method"] == "template_attach"
        assert notification.personalisation["_file_0"]["document"]["file_size"] == 102400
        assert notification.personalisation["_file_1"]["document"]["id"] == "doc-2"
        assert notification.personalisation["_file_1"]["document"]["filename"] == "summary.docx"
        assert notification.personalisation["_file_1"]["document"]["file_size"] == 204800
        # Original personalisation preserved
        assert notification.personalisation["name"] == "Jo"

    def test_does_not_overwrite_existing_file_keys_from_one_off_send(self, sample_service, sample_email_template, mocker):
        """One-off sends already have _file_0 from admin — should not overwrite."""
        notification = save_notification(
            create_notification(
                template=sample_email_template,
                to_field="test@example.com",
                personalisation={
                    "name": "Jo",
                    "_file_0": {
                        "document": {
                            "id": "admin-populated-id",
                            "filename": "admin-file.pdf",
                            "mime_type": "application/pdf",
                            "sending_method": "template_attach",
                        }
                    },
                },
            )
        )

        new_metadata = [
            {
                "name": "different-file.pdf",
                "document_id": "doc-99",
                "mime_type": "application/pdf",
                "service_id": str(sample_service.id),
                "file_id": "file-99",
                "file_size": 1024,
            },
        ]

        send_to_providers._persist_template_attachment_metadata(notification, new_metadata)

        # Should NOT have been overwritten
        assert notification.personalisation["_file_0"]["document"]["id"] == "admin-populated-id"
        assert "_file_1" not in notification.personalisation

    def test_does_nothing_when_no_template_files(self, sample_service, sample_email_template, mocker):
        """No template files means no changes to personalisation."""
        notification = save_notification(
            create_notification(
                template=sample_email_template,
                to_field="test@example.com",
                personalisation={"name": "Jo"},
            )
        )

        send_to_providers._persist_template_attachment_metadata(notification, [])

        assert "_file_0" not in notification.personalisation
        assert notification.personalisation == {"name": "Jo"}

    def test_metadata_persisted_during_send_email_to_provider(
        self, notify_db, notify_db_session, sample_service, sample_email_template, mocker
    ):
        """Integration: send_email_to_provider persists metadata to the database."""
        job = create_sample_job(
            notify_db,
            notify_db_session,
            service=sample_service,
            template=sample_email_template,
        )

        notification = save_notification(
            create_notification(
                template=sample_email_template,
                job=job,
                to_field="test@example.com",
                personalisation={"name": "Jo"},
            )
        )

        file_metadata = [
            {
                "name": "bulk-file.pdf",
                "document_id": "doc-bulk",
                "mime_type": "application/pdf",
                "service_id": str(sample_service.id),
                "file_id": "file-bulk",
                "file_size": 51200,
            },
        ]

        mocker.patch(
            "app.delivery.send_to_providers._get_template_files_from_cache_or_db",
            return_value=file_metadata,
        )
        mocker.patch(
            "app.delivery.send_to_providers._download_template_file",
            return_value={"name": "bulk-file.pdf", "data": b"content", "mime_type": "application/pdf"},
        )
        mocker.patch("app.delivery.send_to_providers.dao_get_template_by_id")
        mocker.patch("app.delivery.send_to_providers.is_service_allowed_html", return_value=False)
        mocker.patch("app.delivery.send_to_providers.get_html_email_options", return_value={})
        mocker.patch("app.delivery.send_to_providers.HTMLEmailTemplate")
        mocker.patch("app.delivery.send_to_providers.PlainTextEmailTemplate")
        mocker.patch("app.delivery.send_to_providers.send_email_response", return_value="ref-123")

        provider_mock = MagicMock()
        provider_mock.send_email.return_value = "ses-ref"
        provider_mock.get_name.return_value = "ses"
        mocker.patch("app.delivery.send_to_providers.provider_to_use", return_value=provider_mock)

        send_to_providers.send_email_to_provider(notification)

        # Reload from DB to verify persistence — not just in-memory state
        from app.dao.notifications_dao import get_notification_by_id

        reloaded = get_notification_by_id(notification.id, _raise=True)
        assert "_file_0" in reloaded.personalisation
        assert reloaded.personalisation["_file_0"]["document"]["id"] == "doc-bulk"
        assert reloaded.personalisation["_file_0"]["document"]["filename"] == "bulk-file.pdf"
        assert reloaded.personalisation["_file_0"]["document"]["sending_method"] == "template_attach"
        assert reloaded.personalisation["_file_0"]["document"]["file_size"] == 51200
        assert reloaded.personalisation["name"] == "Jo"
