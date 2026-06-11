import uuid
from types import SimpleNamespace

from flask import json
from tests import create_authorization_header

from app.models import EMAIL_TYPE, SMS_TYPE


class TestPostTemplateV2ManageTemplate:
    @staticmethod
    def _mock_template_categories(mocker):
        return mocker.patch(
            "app.v2.manage_template.post_template.dao_get_all_template_categories",
            return_value=[SimpleNamespace(id=uuid.uuid4(), name_en="General")],
        )

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
        assert data["service_id"] == str(sample_service.id)
        assert data["service_name"] == sample_service.name
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

    def test_post_email_requires_subject(self, client, sample_template_category, create_api_key_with_manage_api_perm):
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
        assert "service_id" in data
        assert "service_name" in data
        assert data["subject"] == payload["subject"]

    def test_post_template_requires_template_category_id(self, client, create_api_key_with_manage_api_perm, mocker):
        self._mock_template_categories(mocker)

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
        data = json.loads(response.get_data(as_text=True))
        assert data["errors"][0]["error"] == "TemplateCategoryValidationError"
        assert data["errors"][0]["message"] == "template_category_id is a required property"
        assert "template_categories" in data
        assert len(data["template_categories"]) > 0
        assert "template_category_id" in data["template_categories"][0]
        assert "name" in data["template_categories"][0]

    def test_post_template_returns_400_for_invalid_template_category_id(
        self, client, create_api_key_with_manage_api_perm, mocker
    ):
        self._mock_template_categories(mocker)

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
        assert "template_categories" in data
        assert len(data["template_categories"]) > 0
        assert "template_category_id" in data["template_categories"][0]
        assert "name" in data["template_categories"][0]

    def test_post_template_returns_400_with_categories_for_invalid_template_category_uuid(
        self, client, create_api_key_with_manage_api_perm, mocker
    ):
        self._mock_template_categories(mocker)

        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)
        payload = {
            "name": "Invalid UUID Category",
            "template_type": SMS_TYPE,
            "content": "Hello",
            "template_category_id": "not-a-valid-uuid",
        }

        response = client.post(
            "/v2/manage-template",
            data=json.dumps(payload),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 400
        data = json.loads(response.get_data(as_text=True))
        assert data["errors"][0]["error"] == "TemplateCategoryValidationError"
        assert "template_category_id" in data["errors"][0]["message"]
        assert "template_categories" in data
        assert len(data["template_categories"]) > 0

    def test_post_template_deletes_service_templates_cache(
        self, client, sample_service, sample_template_category, create_api_key_with_manage_api_perm, mocker
    ):
        mock_redis_delete = mocker.patch("app.v2.manage_template.post_template.redis_store.delete")
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)
        payload = {
            "name": "Cache Bust Template",
            "template_type": SMS_TYPE,
            "content": "Hello",
            "template_category_id": str(sample_template_category.id),
        }

        response = client.post(
            "/v2/manage-template",
            data=json.dumps(payload),
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 201
        mock_redis_delete.assert_called_once_with(f"service-{sample_service.id}-templates")
