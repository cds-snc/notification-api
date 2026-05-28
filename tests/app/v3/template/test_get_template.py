import uuid

from flask import json
from notifications_python_client.authentication import create_jwt_token

from app.models import EMAIL_TYPE, SMS_TYPE
from tests.app.db import create_service, create_template


def _auth_header(api_key):
    token = create_jwt_token(secret=api_key.secret, client_id=str(api_key.service_id))
    return "Authorization", f"Bearer {token}"


class TestGetTemplateV3:
    def test_get_template_returns_200_with_manage_templates_permission(
        self, client, sample_service, create_api_key_with_manage_api_perm
    ):
        template = create_template(sample_service, template_type=SMS_TYPE)
        auth_header = _auth_header(create_api_key_with_manage_api_perm)

        response = client.get(
            f"/v3/template/{template.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["id"] == str(template.id)
        assert data["name"] == template.name
        assert data["type"] == SMS_TYPE
        assert data["body"] == template.content
        assert data["archived"] is False

    def test_get_template_returns_richer_fields_than_v2(self, client, sample_service, create_api_key_with_manage_api_perm):
        template = create_template(sample_service, template_type=EMAIL_TYPE, subject="Hello")
        auth_header = _auth_header(create_api_key_with_manage_api_perm)

        response = client.get(
            f"/v3/template/{template.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))

        # Fields present in v3 but NOT in v2
        assert "archived" in data
        assert "template_category_id" in data
        assert "folder_id" in data

        # process_type is intentionally NOT exposed in v3
        assert "process_type" not in data

        # Core fields still present
        assert "id" in data
        assert "name" in data
        assert "type" in data
        assert "body" in data
        assert "subject" in data
        assert "created_at" in data
        assert "updated_at" in data
        assert "created_by" in data
        assert "version" in data
        assert "postage" in data

    def test_get_template_returns_403_without_manage_templates_permission(self, client, sample_service, create_api_key_no_perm):
        template = create_template(sample_service, template_type=SMS_TYPE)
        auth_header = _auth_header(create_api_key_no_perm)

        response = client.get(
            f"/v3/template/{template.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 403
        data = json.loads(response.get_data(as_text=True))
        message = data["errors"][0]["message"].lower()
        assert "manage templates" in message or "manage_templates" in message

    def test_get_template_returns_404_for_nonexistent_template(self, client, sample_service, create_api_key_with_manage_api_perm):
        nonexistent_id = uuid.uuid4()
        auth_header = _auth_header(create_api_key_with_manage_api_perm)

        response = client.get(
            f"/v3/template/{nonexistent_id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 404

    def test_get_template_returns_404_for_template_belonging_to_other_service(
        self, client, sample_service, create_api_key_with_manage_api_perm
    ):
        """Templates from other services must not be accessible."""
        other_service = create_service(service_name=f"other service {uuid.uuid4()}")
        other_template = create_template(other_service, template_type=SMS_TYPE)
        auth_header = _auth_header(create_api_key_with_manage_api_perm)

        response = client.get(
            f"/v3/template/{other_template.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 404

    def test_get_sms_template_has_null_subject(self, client, sample_service, create_api_key_with_manage_api_perm):
        template = create_template(sample_service, template_type=SMS_TYPE)
        auth_header = _auth_header(create_api_key_with_manage_api_perm)

        response = client.get(
            f"/v3/template/{template.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["subject"] is None

    def test_get_email_template_has_subject(self, client, sample_service, create_api_key_with_manage_api_perm):
        template = create_template(sample_service, template_type=EMAIL_TYPE, subject="Test subject")
        auth_header = _auth_header(create_api_key_with_manage_api_perm)

        response = client.get(
            f"/v3/template/{template.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["subject"] == "Test subject"

    def test_get_archived_template_returns_archived_true(self, client, sample_service, create_api_key_with_manage_api_perm):
        template = create_template(sample_service, template_type=SMS_TYPE, archived=True)
        auth_header = _auth_header(create_api_key_with_manage_api_perm)

        response = client.get(
            f"/v3/template/{template.id}",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["archived"] is True
