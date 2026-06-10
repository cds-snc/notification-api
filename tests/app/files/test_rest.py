import base64

import pytest
from jsonschema import ValidationError

from app.dao.permissions_dao import permission_dao
from app.files.rest import _parse_scan_verdict_payload
from app.models import FILE_STATUS_UPLOADED
from tests.app.conftest import create_sample_template
from tests.app.db import create_user


class TestCreateFile:
    def test_create_file(self, mocker, notify_db, notify_db_session, admin_request, sample_service_full_permissions):
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
                "file_data": base64.b64encode(
                    b"As I write code by hand, I look back at my AI and wonder, do they miss my prompts?"
                ).decode("utf-8"),
                "created_by": current_user_id,
            },
            _expected_status=201,
        )

    def test_create_file_missing_required(self, notify_db, notify_db_session, admin_request, sample_service):
        sample_template = create_sample_template(notify_db, notify_db_session, service=sample_service)

        admin_request.post(
            "files.create_file",
            template_id=str(sample_template.id),
            _data={},
            _expected_status=400,
        )

    def test_create_file_returns_400_when_created_by_missing(
        self, notify_db, notify_db_session, admin_request, sample_service_full_permissions
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


class TestUpdateFileStatus:
    def test_update_file_status(self, admin_request, sample_file):
        admin_request.post(
            "files.update_file_status",
            template_id=str(sample_file.template_id),
            file_id=str(sample_file.id),
            _data={"status": "uploaded"},
            _expected_status=200,
        )
        assert sample_file.status == FILE_STATUS_UPLOADED

    def test_update_file_status_returns_404_when_template_file_mismatch(
        self, notify_db, notify_db_session, admin_request, sample_file, sample_service_full_permissions
    ):
        different_template = create_sample_template(notify_db, notify_db_session, service=sample_service_full_permissions)

        admin_request.post(
            "files.update_file_status",
            template_id=str(different_template.id),
            file_id=str(sample_file.id),
            _data={"status": "uploaded"},
            _expected_status=404,
        )


class TestDeleteFile:
    def test_delete_file(self, admin_request, sample_file):
        admin_request.delete(
            "files.delete_file",
            template_id=str(sample_file.template_id),
            file_id=str(sample_file.id),
            _expected_status=204,
        )

    def test_delete_file_returns_404_when_template_file_mismatch(
        self, notify_db, notify_db_session, admin_request, sample_file, sample_service_full_permissions
    ):
        different_template = create_sample_template(notify_db, notify_db_session, service=sample_service_full_permissions)

        admin_request.delete(
            "files.delete_file",
            template_id=str(different_template.id),
            file_id=str(sample_file.id),
            _expected_status=404,
        )


class TestParseScanVerdictPayload:
    def test_parse_scan_verdict_payload_accepts_extra_fields(self, client):
        payload = {
            "scan_status": "COMPLETED",
            "scan_result_status": "NO_THREATS_FOUND",
            "object_key": "template/11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222",
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

    def test_parse_scan_verdict_payload_raises_on_unparseable_object_key(self, client):
        payload = {
            "scan_status": "COMPLETED",
            "scan_result_status": "THREATS_FOUND",
            "object_key": "bad/key/format",
            "bucket_name": "my-bucket",
        }

        with pytest.raises(ValidationError, match="objectKey"):
            _parse_scan_verdict_payload(payload)

    def test_parse_scan_verdict_payload_accepts_object_key_with_leading_slash(self, client):
        payload = {
            "scan_status": "COMPLETED",
            "scan_result_status": "NO_THREATS_FOUND",
            "object_key": "/template/11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222",
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
