from flask import json
from tests import create_authorization_header

from app.models import EMAIL_TYPE, SMS_TYPE


class TestPostTemplateV2ManageTemplate:
    def test_post_template_returns_201_with_manage_templates_permission(
        self, client, sample_service, sample_template_category, create_api_key_with_manage_api_perm
    ):
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)
        payload = {
            "name": "New API Template",
            "template_type": SMS_TYPE,
            "content": "Hello from API",
            "template_category_id": str(sample_template_category.id),
        }

        response = client.post(
            "/v2/manage-template",
            data=json.dumps(payload),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 201
        data = json.loads(response.get_data(as_text=True))
        assert data["name"] == payload["name"]
        assert data["type"] == payload["template_type"]
        assert data["body"] == payload["content"]
        assert data["subject"] is None

    def test_post_template_returns_403_without_manage_templates_permission(
        self, client, sample_template_category, create_api_key_no_perm
    ):
        auth_header = create_authorization_header(api_key=create_api_key_no_perm)
        payload = {
            "name": "No Permission Template",
            "template_type": SMS_TYPE,
            "content": "Hello",
            "template_category_id": str(sample_template_category.id),
        }

        response = client.post(
            "/v2/manage-template",
            data=json.dumps(payload),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 403
        data = json.loads(response.get_data(as_text=True))
        assert "manage templates" in data["errors"][0]["message"].lower()

    def test_post_email_or_letter_requires_subject(self, client, sample_template_category, create_api_key_with_manage_api_perm):
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.post(
            "/v2/manage-template",
            data=json.dumps(
                {
                    "name": "Missing Subject",
                    "template_type": EMAIL_TYPE,
                    "content": "Body",
                    "template_category_id": str(sample_template_category.id),
                }
            ),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400

    def test_post_email_template_with_subject_returns_201(
        self, client, sample_template_category, create_api_key_with_manage_api_perm
    ):
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)
        payload = {
            "name": "Email Template",
            "template_type": EMAIL_TYPE,
            "subject": "Email subject",
            "content": "Email body",
            "template_category_id": str(sample_template_category.id),
        }

        response = client.post(
            "/v2/manage-template",
            data=json.dumps(payload),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 201
        data = json.loads(response.get_data(as_text=True))
        assert data["subject"] == payload["subject"]

    def test_post_template_requires_template_category_id(self, client, create_api_key_with_manage_api_perm):
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)
        payload = {
            "name": "Missing Category",
            "template_type": SMS_TYPE,
            "content": "Hello",
        }

        response = client.post(
            "/v2/manage-template",
            data=json.dumps(payload),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400

    def test_post_template_returns_400_for_invalid_template_category_id(self, client, create_api_key_with_manage_api_perm):
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)
        payload = {
            "name": "Invalid Category",
            "template_type": SMS_TYPE,
            "content": "Hello",
            "template_category_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        }

        response = client.post(
            "/v2/manage-template",
            data=json.dumps(payload),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400
        data = json.loads(response.get_data(as_text=True))
        assert data["errors"][0]["message"] == "template_category_id not found"
