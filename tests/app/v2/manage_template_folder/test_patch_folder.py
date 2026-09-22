import uuid

from flask import json
from tests import create_authorization_header
from tests.app.db import create_service, create_template_folder

from app.dao.template_folder_dao import dao_get_template_folder_by_id_and_service_id


class TestPatchTemplateFolderV2:
    def test_rename_folder_returns_200(self, client, sample_service, create_api_key_with_manage_api_perm):
        folder = create_template_folder(sample_service, name="old name")
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template-folder/{folder.id}",
            data=json.dumps({"name": "new name"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["name"] == "new name"

    def test_move_folder_into_parent(self, client, sample_service, create_api_key_with_manage_api_perm):
        parent = create_template_folder(sample_service, name="parent")
        folder = create_template_folder(sample_service, name="child")
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template-folder/{folder.id}",
            data=json.dumps({"parent_folder_id": str(parent.id)}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["parent_folder_id"] == str(parent.id)

    def test_move_folder_to_root(self, client, sample_service, create_api_key_with_manage_api_perm):
        parent = create_template_folder(sample_service, name="parent")
        folder = create_template_folder(sample_service, name="child", parent=parent)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template-folder/{folder.id}",
            data=json.dumps({"parent_folder_id": None}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["parent_folder_id"] is None

    def test_rename_and_move_together(self, client, sample_service, create_api_key_with_manage_api_perm):
        parent = create_template_folder(sample_service, name="parent")
        folder = create_template_folder(sample_service, name="child")
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template-folder/{folder.id}",
            data=json.dumps({"name": "renamed", "parent_folder_id": str(parent.id)}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        updated = dao_get_template_folder_by_id_and_service_id(folder.id, sample_service.id)
        assert updated.name == "renamed"
        assert str(updated.parent_id) == str(parent.id)

    def test_move_folder_to_itself_returns_400(self, client, sample_service, create_api_key_with_manage_api_perm):
        folder = create_template_folder(sample_service, name="folder")
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template-folder/{folder.id}",
            data=json.dumps({"parent_folder_id": str(folder.id)}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400
        data = json.loads(response.get_data(as_text=True))
        assert "move a folder to itself" in data["errors"][0]["message"]

    def test_move_folder_into_own_subfolder_returns_400(self, client, sample_service, create_api_key_with_manage_api_perm):
        parent = create_template_folder(sample_service, name="parent")
        child = create_template_folder(sample_service, name="child", parent=parent)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template-folder/{parent.id}",
            data=json.dumps({"parent_folder_id": str(child.id)}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400
        data = json.loads(response.get_data(as_text=True))
        assert "one of its subfolders" in data["errors"][0]["message"]

    def test_move_to_unknown_parent_returns_400(self, client, sample_service, create_api_key_with_manage_api_perm):
        folder = create_template_folder(sample_service, name="folder")
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template-folder/{folder.id}",
            data=json.dumps({"parent_folder_id": str(uuid.uuid4())}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400
        data = json.loads(response.get_data(as_text=True))
        assert "parent_folder_id not found" in data["errors"][0]["message"]

    def test_patch_folder_returns_403_without_manage_templates_permission(self, client, sample_service, create_api_key_no_perm):
        folder = create_template_folder(sample_service)
        auth_header = create_authorization_header(api_key=create_api_key_no_perm)

        response = client.patch(
            f"/v2/manage-template-folder/{folder.id}",
            data=json.dumps({"name": "nope"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 403
        data = json.loads(response.get_data(as_text=True))
        assert "manage templates" in data["errors"][0]["message"].lower()

    def test_patch_folder_returns_404_for_nonexistent_folder(self, client, sample_service, create_api_key_with_manage_api_perm):
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template-folder/{uuid.uuid4()}",
            data=json.dumps({"name": "nope"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 404

    def test_patch_folder_returns_404_for_folder_belonging_to_other_service(
        self, client, sample_service, create_api_key_with_manage_api_perm
    ):
        other_service = create_service(service_name=f"other service {uuid.uuid4()}")
        other_folder = create_template_folder(other_service)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template-folder/{other_folder.id}",
            data=json.dumps({"name": "nope"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 404
