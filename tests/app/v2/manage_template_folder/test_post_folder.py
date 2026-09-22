import uuid

from flask import json
from tests import create_authorization_header
from tests.app.db import create_template_folder

from app.dao.template_folder_dao import dao_get_template_folder_by_id_and_service_id


class TestPostTemplateFolderV2:
    def test_create_root_folder_returns_201(self, client, sample_service, create_api_key_with_manage_api_perm):
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.post(
            "/v2/manage-template-folder",
            data=json.dumps({"name": "new folder"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 201
        data = json.loads(response.get_data(as_text=True))
        assert data["name"] == "new folder"
        assert data["service_id"] == str(sample_service.id)
        assert data["parent_folder_id"] is None

    def test_create_root_folder_shares_with_active_service_users(
        self, client, sample_service, create_api_key_with_manage_api_perm
    ):
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.post(
            "/v2/manage-template-folder",
            data=json.dumps({"name": "shared folder"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 201
        data = json.loads(response.get_data(as_text=True))
        expected_users = {str(user.id) for user in sample_service.users}
        assert set(data["users_with_permission"]) == expected_users

    def test_create_subfolder_inherits_parent_permissions(self, client, sample_service, create_api_key_with_manage_api_perm):
        parent = create_template_folder(sample_service, name="parent")
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.post(
            "/v2/manage-template-folder",
            data=json.dumps({"name": "child", "parent_folder_id": str(parent.id)}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 201
        data = json.loads(response.get_data(as_text=True))
        assert data["parent_folder_id"] == str(parent.id)
        assert set(data["users_with_permission"]) == set(parent.get_users_with_permission())

    def test_create_folder_persists_to_db(self, client, sample_service, create_api_key_with_manage_api_perm):
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.post(
            "/v2/manage-template-folder",
            data=json.dumps({"name": "  trimmed  "}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 201
        data = json.loads(response.get_data(as_text=True))
        folder = dao_get_template_folder_by_id_and_service_id(data["id"], sample_service.id)
        assert folder.name == "trimmed"

    def test_create_folder_returns_400_for_missing_name(self, client, sample_service, create_api_key_with_manage_api_perm):
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.post(
            "/v2/manage-template-folder",
            data=json.dumps({}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400

    def test_create_folder_returns_400_for_empty_name(self, client, sample_service, create_api_key_with_manage_api_perm):
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.post(
            "/v2/manage-template-folder",
            data=json.dumps({"name": ""}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400

    def test_create_folder_returns_400_for_unknown_parent(self, client, sample_service, create_api_key_with_manage_api_perm):
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.post(
            "/v2/manage-template-folder",
            data=json.dumps({"name": "orphan", "parent_folder_id": str(uuid.uuid4())}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400
        data = json.loads(response.get_data(as_text=True))
        assert "parent_folder_id not found" in data["errors"][0]["message"]

    def test_create_folder_returns_403_without_manage_templates_permission(self, client, sample_service, create_api_key_no_perm):
        auth_header = create_authorization_header(api_key=create_api_key_no_perm)

        response = client.post(
            "/v2/manage-template-folder",
            data=json.dumps({"name": "no perm"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 403
        data = json.loads(response.get_data(as_text=True))
        assert "manage templates" in data["errors"][0]["message"].lower()
