import base64
import json
import uuid

import pytest
from flask import current_app, url_for

from app.dao.permissions_dao import permission_dao
from app.files.rest import _parse_scan_verdict_payload
from app.models import FILE_STATUS_UPLOADED, FILE_STATUS_VIRUS_SCAN_FAILED
from tests.app.conftest import create_sample_template
from tests.app.db import create_user
from tests.conftest import set_config_values

MOCK_DOCUMENT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _mock_upload_template_attachment(mocker, document_id=MOCK_DOCUMENT_ID):
    """Mock document_download_client.upload_template_attachment to return a fake document response."""
    return mocker.patch(
        "app.files.rest.document_download_client.upload_template_attachment",
        return_value={
            "status": "ok",
            "document": {
                "id": document_id,
                "direct_file_url": "http://localhost:7000/services/test/documents/test",
                "url": "http://localhost:7000/d/test/test",
                "filename": "test.pdf",
                "sending_method": "template_attach",
                "mime_type": "application/pdf",
                "file_size": 12345,
                "file_extension": "pdf",
            },
        },
    )


class TestCreateFile:
    def test_create_file(self, mocker, notify_db, notify_db_session, admin_request, sample_service_full_permissions):
        mock_upload = _mock_upload_template_attachment(mocker)
        sample_template = create_sample_template(notify_db, notify_db_session, service=sample_service_full_permissions)
        current_user_id = str(sample_template.service.users[0].id)
        raw_content = b"As I write code by hand, I look back at my AI and wonder, do they miss my prompts!"

        response = admin_request.post(
            "files.create_file",
            template_id=str(sample_template.id),
            _data={
                "template_id": str(sample_template.id),
                "type": "attach",
                "name": "test.pdf",
                "mime_type": "application/pdf",
                "file_size": 12345,
                "file_data": base64.b64encode(raw_content).decode("utf-8"),
                "created_by": current_user_id,
            },
            _expected_status=201,
        )
        assert response["document_id"] == MOCK_DOCUMENT_ID
        mock_upload.assert_called_once_with(sample_template.service.id, raw_content, "test.pdf", "application/pdf")

    def test_create_file_stores_document_id_from_dd_api(
        self, mocker, notify_db, notify_db_session, admin_request, sample_service_full_permissions
    ):
        """Verify the document_id stored in DB comes from dd-api, not locally generated."""
        custom_doc_id = str(uuid.uuid4())
        mock_upload = _mock_upload_template_attachment(mocker, document_id=custom_doc_id)
        sample_template = create_sample_template(notify_db, notify_db_session, service=sample_service_full_permissions)
        current_user_id = str(sample_template.service.users[0].id)
        raw_content = b"test content"

        response = admin_request.post(
            "files.create_file",
            template_id=str(sample_template.id),
            _data={
                "template_id": str(sample_template.id),
                "type": "attach",
                "name": "test.pdf",
                "mime_type": "application/pdf",
                "file_size": 12345,
                "file_data": base64.b64encode(raw_content).decode("utf-8"),
                "created_by": current_user_id,
            },
            _expected_status=201,
        )
        assert response["document_id"] == custom_doc_id
        mock_upload.assert_called_once_with(sample_template.service.id, raw_content, "test.pdf", "application/pdf")

    def test_create_file_returns_503_when_dd_api_fails(
        self, mocker, notify_db, notify_db_session, admin_request, sample_service_full_permissions
    ):
        """Verify that a DocumentDownloadError from dd-api results in an error response."""
        from app.clients.document_download import DocumentDownloadError

        mocker.patch(
            "app.files.rest.document_download_client.upload_template_attachment",
            side_effect=DocumentDownloadError(message="Upload failed", status_code=503),
        )
        sample_template = create_sample_template(notify_db, notify_db_session, service=sample_service_full_permissions)
        current_user_id = str(sample_template.service.users[0].id)

        admin_request.post(
            "files.create_file",
            template_id=str(sample_template.id),
            _data={
                "template_id": str(sample_template.id),
                "type": "attach",
                "name": "test.pdf",
                "mime_type": "application/pdf",
                "file_size": 12345,
                "file_data": base64.b64encode(b"test content").decode("utf-8"),
                "created_by": current_user_id,
            },
            _expected_status=503,
        )

    def test_create_file_missing_required(self, mocker, notify_db, notify_db_session, admin_request, sample_service):
        sample_template = create_sample_template(notify_db, notify_db_session, service=sample_service)

        admin_request.post(
            "files.create_file",
            template_id=str(sample_template.id),
            _data={},
            _expected_status=400,
        )

    def test_create_file_returns_400_when_created_by_missing(
        self, mocker, notify_db, notify_db_session, admin_request, sample_service_full_permissions
    ):
        sample_template = create_sample_template(notify_db, notify_db_session, service=sample_service_full_permissions)

        admin_request.post(
            "files.create_file",
            template_id=str(sample_template.id),
            _data={
                "template_id": str(sample_template.id),
                "type": "attach",
                "name": "test.pdf",
                "mime_type": "application/pdf",
                "file_size": 12345,
                "file_data": base64.b64encode(
                    b"As I write code by hand, I look back at my AI and wonder, do they miss my prompts?"
                ).decode("utf-8"),
                "current_user": str(sample_template.service.users[0].id),
            },
            _expected_status=400,
        )

    def test_create_file_returns_403_when_user_lacks_manage_templates(
        self, notify_db, notify_db_session, admin_request, sample_service_full_permissions
    ):
        sample_template = create_sample_template(notify_db, notify_db_session, service=sample_service_full_permissions)
        user_without_permissions = create_user(email="no.file.permission@cds-snc.ca")

        admin_request.post(
            "files.create_file",
            template_id=str(sample_template.id),
            _data={
                "template_id": str(sample_template.id),
                "type": "attach",
                "name": "test.pdf",
                "mime_type": "application/pdf",
                "file_size": 12345,
                "file_data": base64.b64encode(
                    b"As I write code by hand, I look back at my AI and wonder, do they miss my prompts?"
                ).decode("utf-8"),
                "created_by": str(user_without_permissions.id),
                "current_user": str(user_without_permissions.id),
            },
            _expected_status=403,
        )

    def test_create_file_returns_403_when_manage_templates_removed(
        self, notify_db, notify_db_session, admin_request, sample_service_full_permissions
    ):
        sample_template = create_sample_template(notify_db, notify_db_session, service=sample_service_full_permissions)
        current_user = sample_template.service.users[0]
        permission_dao.remove_user_service_permissions_for_all_services(current_user)

        admin_request.post(
            "files.create_file",
            template_id=str(sample_template.id),
            _data={
                "template_id": str(sample_template.id),
                "type": "attach",
                "name": "test.pdf",
                "mime_type": "application/pdf",
                "file_size": 12345,
                "file_data": base64.b64encode(
                    b"As I write code by hand, I look back at my AI and wonder, do they miss my prompts?"
                ).decode("utf-8"),
                "created_by": str(current_user.id),
                "current_user": str(current_user.id),
            },
            _expected_status=403,
        )


class TestGetFile:
    def test_get_file_status(self, admin_request, sample_file):
        response = admin_request.get(
            "files.get_file_status",
            template_id=str(sample_file.template_id),
            file_id=str(sample_file.id),
            _expected_status=200,
        )
        assert response["status"] == sample_file.status

    def test_get_files_by_template_id(self, admin_request, sample_file):
        admin_request.get(
            "files.get_files_by_template_id",
            template_id=str(sample_file.template_id),
            _expected_status=200,
        )


SCAN_VERDICT_TOKEN = "test-scan-verdict-token"


def _scan_verdict_post(client, data, expected_status=200):
    """POST to the scan-verdict-callback endpoint with the X-Scan-Callback-Token header."""
    with set_config_values(current_app, {"SCAN_VERDICT_CALLBACK_TOKEN": SCAN_VERDICT_TOKEN}):
        resp = client.post(
            url_for("scan_verdict_callback.update_file_status"),
            data=json.dumps(data),
            headers=[
                ("Content-Type", "application/json"),
                ("X-Scan-Callback-Token", SCAN_VERDICT_TOKEN),
            ],
        )
    assert resp.status_code == expected_status, resp.json
    return resp.json


class TestUpdateFileStatus:
    @pytest.fixture(autouse=True)
    def mock_delete_document(self, mocker):
        return mocker.patch("app.files.rest.document_download_client.delete_document")

    def test_update_file_status_clean_scan(self, client, sample_file, mock_delete_document):
        data = {
            "scan_status": "COMPLETED",
            "scan_result_status": "NO_THREATS_FOUND",
            "object_key": f"template_attachments/{sample_file.service_id}/{sample_file.document_id}",
            "bucket_name": "test-bucket",
        }
        resp = _scan_verdict_post(client, data)

        assert resp["status"] == FILE_STATUS_UPLOADED
        assert sample_file.status == FILE_STATUS_UPLOADED
        mock_delete_document.assert_called_once_with(str(sample_file.service_id), str(sample_file.document_id), "template_attach")

    def test_update_file_status_threat_found(self, client, sample_file):
        data = {
            "scan_status": "COMPLETED",
            "scan_result_status": "THREATS_FOUND",
            "object_key": f"template_attachments/{sample_file.service_id}/{sample_file.document_id}",
            "bucket_name": "test-bucket",
        }
        resp = _scan_verdict_post(client, data)

        assert resp["status"] == FILE_STATUS_VIRUS_SCAN_FAILED
        assert sample_file.status == FILE_STATUS_VIRUS_SCAN_FAILED

    def test_update_file_status_scan_failure_maps_to_terminal(self, client, sample_file):
        data = {
            "scan_status": "FAILED",
            "object_key": f"template_attachments/{sample_file.service_id}/{sample_file.document_id}",
            "bucket_name": "test-bucket",
        }
        resp = _scan_verdict_post(client, data)

        assert resp["status"] == FILE_STATUS_VIRUS_SCAN_FAILED
        assert sample_file.status == FILE_STATUS_VIRUS_SCAN_FAILED

    def test_update_file_status_returns_404_for_unknown_document_id(self, client, sample_file):
        data = {
            "scan_status": "COMPLETED",
            "scan_result_status": "NO_THREATS_FOUND",
            "object_key": f"template_attachments/{sample_file.service_id}/{uuid.uuid4()}",
            "bucket_name": "test-bucket",
        }
        _scan_verdict_post(client, data, expected_status=404)

    def test_update_file_status_returns_404_for_service_id_mismatch(self, client, sample_file):
        wrong_service_id = str(uuid.uuid4())
        data = {
            "scan_status": "COMPLETED",
            "scan_result_status": "NO_THREATS_FOUND",
            "object_key": f"template_attachments/{wrong_service_id}/{sample_file.document_id}",
            "bucket_name": "test-bucket",
        }
        _scan_verdict_post(client, data, expected_status=404)

    def test_update_file_status_returns_400_for_invalid_schema(self, client, sample_file):
        _scan_verdict_post(client, {"unexpected": "payload"}, expected_status=400)

    def test_update_file_status_returns_401_without_token(self, client, sample_file):
        resp = client.post(
            url_for("scan_verdict_callback.update_file_status"),
            data=json.dumps({"scan_status": "COMPLETED"}),
            headers=[("Content-Type", "application/json")],
        )
        assert resp.status_code == 401

    def test_update_file_status_returns_403_for_wrong_token(self, client, sample_file):
        resp = client.post(
            url_for("scan_verdict_callback.update_file_status"),
            data=json.dumps({"scan_status": "COMPLETED"}),
            headers=[
                ("Content-Type", "application/json"),
                ("X-Scan-Callback-Token", "wrong-token"),
            ],
        )
        assert resp.status_code == 401


class TestDeleteFile:
    def test_delete_file(self, mocker, admin_request, sample_file):
        # Mock the document_download_client
        mock_delete = mocker.patch("app.files.rest.document_download_client.delete_document")

        admin_request.delete(
            "files.delete_file",
            template_id=str(sample_file.template_id),
            file_id=str(sample_file.id),
            _expected_status=204,
        )

        # Verify S3 delete was called with sending_method
        mock_delete.assert_called_once_with(sample_file.service_id, sample_file.document_id, sample_file.type)

    def test_delete_file_returns_404_when_template_file_mismatch(
        self, mocker, notify_db, notify_db_session, admin_request, sample_file, sample_service_full_permissions
    ):
        # Mock the document_download_client (shouldn't be called due to 404)
        mock_delete = mocker.patch("app.files.rest.document_download_client.delete_document")

        different_template = create_sample_template(notify_db, notify_db_session, service=sample_service_full_permissions)

        admin_request.delete(
            "files.delete_file",
            template_id=str(different_template.id),
            file_id=str(sample_file.id),
            _expected_status=404,
        )

        # Verify S3 delete was NOT called (failed before reaching that code)
        mock_delete.assert_not_called()

    def test_delete_file_fails_when_s3_deletion_fails(self, mocker, notify_db_session, admin_request, sample_file):
        # Mock the document_download_client to raise an error
        from app.clients.document_download import DocumentDownloadError

        mock_delete = mocker.patch("app.files.rest.document_download_client.delete_document")
        mock_delete.side_effect = DocumentDownloadError("S3 deletion failed", 500)

        # Attempt to delete should fail
        response = admin_request.delete(
            "files.delete_file",
            template_id=str(sample_file.template_id),
            file_id=str(sample_file.id),
            _expected_status=500,
        )

        # Verify the error message
        assert "Failed to delete file from storage" in response["message"]

        # Verify S3 delete was attempted with sending_method
        mock_delete.assert_called_once_with(sample_file.service_id, sample_file.document_id, sample_file.type)

        # Verify the file still exists in the database
        from app.dao.files_dao import dao_get_file_by_id

        db_file = dao_get_file_by_id(sample_file.id)
        assert db_file is not None
        assert db_file.id == sample_file.id


class TestParseScanVerdictPayload:
    def test_parse_scan_verdict_payload_accepts_extra_fields(self, client):
        payload = {
            "scan_status": "COMPLETED",
            "scan_result_status": "NO_THREATS_FOUND",
            "object_key": "template_attachments/11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222",
            "bucket_name": "my-bucket",
            "top_level": "ignored",
        }

        parsed = _parse_scan_verdict_payload(payload)

        assert parsed == {
            "status": "ok",
            "service_id": "11111111-1111-1111-1111-111111111111",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "new_status": "uploaded",
        }

    def test_parse_scan_verdict_payload_accepts_object_key_with_leading_slash(self, client):
        payload = {
            "scan_status": "COMPLETED",
            "scan_result_status": "NO_THREATS_FOUND",
            "object_key": "/template_attachments/11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222",
            "bucket_name": "my-bucket",
        }

        parsed = _parse_scan_verdict_payload(payload)

        assert parsed == {
            "status": "ok",
            "service_id": "11111111-1111-1111-1111-111111111111",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "new_status": "uploaded",
        }

    def test_parse_scan_verdict_payload_maps_failed_scan_to_terminal_status(self, client):
        payload = {
            "scan_status": "FAILED",
            "object_key": "template_attachments/11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222",
            "bucket_name": "my-bucket",
        }

        parsed = _parse_scan_verdict_payload(payload)

        assert parsed == {
            "status": "ok",
            "service_id": "11111111-1111-1111-1111-111111111111",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "new_status": "virus_scan_failed",
        }

    def test_parse_scan_verdict_payload_completed_with_unknown_scan_result_falls_back_to_terminal_status(self, client):
        payload = {
            "scan_status": "COMPLETED",
            "scan_result_status": "SOMETHING_NEW",
            "object_key": "template_attachments/11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222",
            "bucket_name": "my-bucket",
        }

        parsed = _parse_scan_verdict_payload(payload)

        assert parsed == {
            "status": "ok",
            "service_id": "11111111-1111-1111-1111-111111111111",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "new_status": "virus_scan_failed",
        }

    def test_parse_scan_verdict_payload_completed_without_scan_result_falls_back_to_terminal_status(self, client):
        payload = {
            "scan_status": "COMPLETED",
            "object_key": "template/11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222",
            "bucket_name": "my-bucket",
        }

        parsed = _parse_scan_verdict_payload(payload)

        assert parsed == {
            "status": "ok",
            "service_id": "11111111-1111-1111-1111-111111111111",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "new_status": "virus_scan_failed",
        }
