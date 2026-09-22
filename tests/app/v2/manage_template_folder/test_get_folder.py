import uuid

from flask import json
from tests import create_authorization_header
from tests.app.db import create_service, create_template_folder


class TestGetTemplateFolderV2:
    def test_list_folders_returns_200(self, client, sample_service, create_api_key_with_manage_api_perm):
        create_template_folder(sample_service, name="folder one")
        create_template_folder(sample_service, name="folder two")
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.get(
            "/v2/manage-template-folder",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        names = {folder["name"] for folder in data["template_folders"]}
        assert {"folder one", "folder two"} <= names

    def test_get_folder_by_id_returns_200(self, client, sample_service, create_api_key_with_manage_api_perm):
        folder = create_template_folder(sample_service, name="my folder")
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.get(
            f"/v2/manage-template-folder/{folder.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["id"] == str(folder.id)
        assert data["service_id"] == str(sample_service.id)
        assert data["name"] == "my folder"
        assert data["parent_folder_id"] is None
        assert "users_with_permission" in data

    def test_get_subfolder_returns_parent_folder_id(self, client, sample_service, create_api_key_with_manage_api_perm):
        parent = create_template_folder(sample_service, name="parent")
        child = create_template_folder(sample_service, name="child", parent=parent)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.get(
            f"/v2/manage-template-folder/{child.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["parent_folder_id"] == str(parent.id)

    def test_get_folder_returns_403_without_manage_templates_permission(self, client, sample_service, create_api_key_no_perm):
        folder = create_template_folder(sample_service)
        auth_header = create_authorization_header(api_key=create_api_key_no_perm)

        response = client.get(
            f"/v2/manage-template-folder/{folder.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 403
        data = json.loads(response.get_data(as_text=True))
        assert "manage templates" in data["errors"][0]["message"].lower()

    def test_get_folder_returns_404_for_nonexistent_folder(self, client, sample_service, create_api_key_with_manage_api_perm):
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.get(
            f"/v2/manage-template-folder/{uuid.uuid4()}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 404

    def test_get_folder_returns_404_for_folder_belonging_to_other_service(
        self, client, sample_service, create_api_key_with_manage_api_perm
    ):
        other_service = create_service(service_name=f"other service {uuid.uuid4()}")
        other_folder = create_template_folder(other_service)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.get(
            f"/v2/manage-template-folder/{other_folder.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 404
