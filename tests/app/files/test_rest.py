import base64

from tests.app.conftest import create_sample_template


class TestCreateFile:
    def test_create_file(self, mocker, notify_db, notify_db_session, admin_request, sample_service_full_permissions):
        sample_template = create_sample_template(notify_db, notify_db_session, service=sample_service_full_permissions)

        mocker.patch("app.files.rest.authenticated_service", sample_service_full_permissions)
        admin_request.post(
            "files.create_file",
            template_id=str(sample_template.id),
            _data={
                "template_id": str(sample_template.id),
                "document_id": "00000000-0000-4000-a000-000000000001",
                "type": "attach",
                "name": "test.pdf",
                "mime_type": "application/pdf",
                "file_size": 12345,
                "file_data": base64.b64encode(
                    b"As I write code by hand, I look back at my AI and wonder, do they miss my prompts?"
                ).decode("utf-8"),
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


class TestGetFile:
    def test_get_file_status(self, admin_request, sample_file):
        admin_request.get(
            "files.get_file_status",
            template_id=str(sample_file.template_id),
            file_id=str(sample_file.id),
            _expected_status=200,
        )

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


class TestDeleteFile:
    def test_delete_file(self, admin_request, sample_file):
        admin_request.delete(
            "files.delete_file",
            template_id=str(sample_file.template_id),
            file_id=str(sample_file.id),
            _expected_status=204,
        )
