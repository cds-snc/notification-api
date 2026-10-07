import uuid

import pytest
from flask import json
from sqlalchemy.orm.exc import NoResultFound
from tests import create_authorization_header
from tests.app.db import create_service, create_template, create_template_folder

from app.dao.template_folder_dao import dao_get_template_folder_by_id_and_service_id


class TestDeleteTemplateFolderV2:
    def test_delete_empty_folder_returns_200(self, client, sample_service, create_api_key_with_manage_api_perm):
        folder = create_template_folder(sample_service, name="to delete")
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.delete(
            f"/v2/manage-template-folder/{folder.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["id"] == str(folder.id)

        with pytest.raises(NoResultFound):
            dao_get_template_folder_by_id_and_service_id(folder.id, sample_service.id)

    def test_delete_folder_with_subfolder_returns_400(self, client, sample_service, create_api_key_with_manage_api_perm):
        parent = create_template_folder(sample_service, name="parent")
        create_template_folder(sample_service, name="child", parent=parent)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.delete(
            f"/v2/manage-template-folder/{parent.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400
        data = json.loads(response.get_data(as_text=True))
        assert "not empty" in data["errors"][0]["message"].lower()

    def test_delete_folder_with_template_returns_400(self, client, sample_service, create_api_key_with_manage_api_perm):
        folder = create_template_folder(sample_service, name="has template")
        create_template(sample_service, folder=folder)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.delete(
            f"/v2/manage-template-folder/{folder.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400
        data = json.loads(response.get_data(as_text=True))
        assert "not empty" in data["errors"][0]["message"].lower()

    def test_delete_folder_returns_403_without_manage_templates_permission(self, client, sample_service, create_api_key_no_perm):
        folder = create_template_folder(sample_service)
        auth_header = create_authorization_header(api_key=create_api_key_no_perm)

        response = client.delete(
            f"/v2/manage-template-folder/{folder.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 403
        data = json.loads(response.get_data(as_text=True))
        assert "manage templates" in data["errors"][0]["message"].lower()

    def test_delete_folder_returns_404_for_nonexistent_folder(self, client, sample_service, create_api_key_with_manage_api_perm):
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.delete(
            f"/v2/manage-template-folder/{uuid.uuid4()}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 404

    def test_delete_folder_returns_404_for_folder_belonging_to_other_service(
        self, client, sample_service, create_api_key_with_manage_api_perm
    ):
        other_service = create_service(service_name=f"other service {uuid.uuid4()}")
        other_folder = create_template_folder(other_service)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.delete(
            f"/v2/manage-template-folder/{other_folder.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 404
