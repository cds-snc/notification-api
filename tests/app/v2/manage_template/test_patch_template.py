import uuid

from flask import json
from tests import create_authorization_header
from tests.app.db import create_template

from app.models import EMAIL_TYPE, SMS_TYPE


class TestPatchTemplateV2ManageTemplate:
    def test_patch_template_updates_name(
        self, client, sample_service, sample_template_category, create_api_key_with_manage_api_perm
    ):
        template = create_template(sample_service, template_type=SMS_TYPE)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template/{template.id}",
            data=json.dumps({"name": "Updated Name"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["name"] == "Updated Name"

    def test_patch_template_updates_content(self, client, sample_service, create_api_key_with_manage_api_perm):
        template = create_template(sample_service, template_type=SMS_TYPE)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template/{template.id}",
            data=json.dumps({"content": "New content body"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["body"] == "New content body"

    def test_patch_template_updates_subject_for_email(self, client, sample_service, create_api_key_with_manage_api_perm):
        template = create_template(sample_service, template_type=EMAIL_TYPE, subject="Old subject")
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template/{template.id}",
            data=json.dumps({"subject": "New subject"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["subject"] == "New subject"

    def test_patch_template_updates_template_category(
        self, client, sample_service, sample_template_category, create_api_key_with_manage_api_perm
    ):
        template = create_template(sample_service, template_type=SMS_TYPE)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template/{template.id}",
            data=json.dumps({"template_category_id": str(sample_template_category.id)}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["template_category_id"] == str(sample_template_category.id)

    def test_patch_template_returns_400_for_invalid_template_category_id(
        self, client, sample_service, create_api_key_with_manage_api_perm, mocker
    ):
        mocker.patch(
            "app.v2.manage_template.patch_template.dao_get_all_template_categories",
            return_value=[],
        )
        template = create_template(sample_service, template_type=SMS_TYPE)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template/{template.id}",
            data=json.dumps({"template_category_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400
        data = json.loads(response.get_data(as_text=True))
        assert data["errors"][0]["message"] == "template_category_id not found"

    def test_patch_template_returns_400_for_invalid_parent_folder_id(
        self, client, sample_service, create_api_key_with_manage_api_perm
    ):
        template = create_template(sample_service, template_type=SMS_TYPE)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template/{template.id}",
            data=json.dumps({"parent_folder_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400
        data = json.loads(response.get_data(as_text=True))
        assert "parent_folder_id not found" in data["errors"][0]["message"]

    def test_patch_template_returns_403_without_manage_templates_permission(self, client, sample_service, create_api_key_no_perm):
        template = create_template(sample_service, template_type=SMS_TYPE)
        auth_header = create_authorization_header(api_key=create_api_key_no_perm)

        response = client.patch(
            f"/v2/manage-template/{template.id}",
            data=json.dumps({"name": "Should fail"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 403
        data = json.loads(response.get_data(as_text=True))
        assert "manage templates" in data["errors"][0]["message"].lower()

    def test_patch_template_returns_404_for_nonexistent_template(
        self, client, sample_service, create_api_key_with_manage_api_perm
    ):
        nonexistent_id = uuid.uuid4()
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template/{nonexistent_id}",
            data=json.dumps({"name": "Should not exist"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 404

    def test_patch_template_returns_400_for_additional_properties(
        self, client, sample_service, create_api_key_with_manage_api_perm
    ):
        template = create_template(sample_service, template_type=SMS_TYPE)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template/{template.id}",
            data=json.dumps({"template_type": SMS_TYPE}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400

    def test_patch_template_returns_serialized_template(self, client, sample_service, create_api_key_with_manage_api_perm):
        template = create_template(sample_service, template_type=SMS_TYPE)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.patch(
            f"/v2/manage-template/{template.id}",
            data=json.dumps({"name": "Patched Template"}),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert "id" in data
        assert "service_id" in data
        assert "service_name" in data
        assert "name" in data
        assert "type" in data
        assert "body" in data
        assert "created_at" in data
        assert "updated_at" in data
        assert "archived" in data
