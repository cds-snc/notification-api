from flask import json
from tests import create_authorization_header


class TestGetTemplateCategoriesV2ManageTemplate:
    def test_get_template_categories_returns_200_with_manage_templates_permission(
        self, client, sample_template_category, create_api_key_with_manage_api_perm
    ):
        auth_header = create_authorization_header(api_key=create_api_key_with_manage_api_perm)

        response = client.get(
            "/v2/manage-template/template-categories",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert "template_categories" in data
        assert len(data["template_categories"]) > 0
        category = data["template_categories"][0]
        assert "template_category_id" in category
        assert "name" in category
        assert "template_type" not in category

    def test_get_template_categories_returns_403_without_manage_templates_permission(self, client, create_api_key_no_perm):
        auth_header = create_authorization_header(api_key=create_api_key_no_perm)

        response = client.get(
            "/v2/manage-template/template-categories",
            headers=[("Content-Type", "application/json"), auth_header],
        )

        assert response.status_code == 403
