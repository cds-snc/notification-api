import uuid

from flask import json
from tests import create_authorization_header
from tests.app.db import create_service, create_template

from app.models import EMAIL_TYPE, SMS_TYPE


class TestDeleteTemplateV2ManageTemplate:
    def test_delete_template_archives_and_returns_200(self, client, sample_service, create_api_key_with_manage_api_perm):
        template = create_template(sample_service, template_type=SMS_TYPE)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.delete(
            f"/v2/manage-template/{template.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["id"] == str(template.id)
        assert data["archived"] is True

    def test_delete_template_returns_serialized_body(self, client, sample_service, create_api_key_with_manage_api_perm):
        template = create_template(sample_service, template_type=EMAIL_TYPE, subject="Subject")
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.delete(
            f"/v2/manage-template/{template.id}",
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
        assert "archived" in data
        assert data["archived"] is True

    def test_delete_already_archived_template_returns_400(self, client, sample_service, create_api_key_with_manage_api_perm):
        template = create_template(sample_service, template_type=SMS_TYPE, archived=True)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.delete(
            f"/v2/manage-template/{template.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400
        data = json.loads(response.get_data(as_text=True))
        assert "already archived" in data["errors"][0]["message"].lower()

    def test_delete_template_returns_403_without_manage_templates_permission(
        self, client, sample_service, create_api_key_no_perm
    ):
        template = create_template(sample_service, template_type=SMS_TYPE)
        auth_header = create_authorization_header(api_key=create_api_key_no_perm)

        response = client.delete(
            f"/v2/manage-template/{template.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 403
        data = json.loads(response.get_data(as_text=True))
        assert "manage templates" in data["errors"][0]["message"].lower()

    def test_delete_template_returns_404_for_nonexistent_template(
        self, client, sample_service, create_api_key_with_manage_api_perm
    ):
        nonexistent_id = uuid.uuid4()
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.delete(
            f"/v2/manage-template/{nonexistent_id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 404

    def test_delete_template_returns_404_for_template_belonging_to_other_service(
        self, client, sample_service, create_api_key_with_manage_api_perm
    ):
        other_service = create_service(service_name=f"other service {uuid.uuid4()}")
        other_template = create_template(other_service, template_type=SMS_TYPE)
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.delete(
            f"/v2/manage-template/{other_template.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 404
