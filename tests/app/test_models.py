from app.models import EMAIL_TYPE, SMS_TYPE
import pytest


class TestTemplateBase:
    @pytest.mark.parametrize(
        'feature_enabled',
        [
            False,
            True,
        ],
    )
    def test_html_property_returns_none_when_feature_flag_disabled(self, mocker, sample_template, feature_enabled):
        """
        Test that TemplateBase.html property returns None when
        STORE_TEMPLATE_CONTENT feature flag is disabled
        """
        mocker.patch('app.models.is_feature_enabled', return_value=feature_enabled)
        mocker.patch('app.dao.templates_dao.is_feature_enabled', return_value=feature_enabled)
        template = sample_template(template_type=EMAIL_TYPE)
        template.content_as_html = '<p>Some HTML content</p>'

        if not feature_enabled:
            assert template.html is None
        else:
            assert template.html == '<p>Some HTML content</p>'

    @pytest.mark.parametrize(
        'template_type, expected_html',
        [
            (EMAIL_TYPE, '<p>Some HTML content</p>'),
            (SMS_TYPE, None),
        ],
    )
    def test_html_property_by_template_type(self, mocker, sample_template, template_type, expected_html):
        """
        Test that TemplateBase.html property behaves correctly based on template type
        when STORE_TEMPLATE_CONTENT feature flag is enabled
        """
        mocker.patch('app.models.is_feature_enabled', return_value=True)
        mocker.patch('app.dao.templates_dao.is_feature_enabled', return_value=True)

        template = sample_template(template_type=template_type)

        if template_type == EMAIL_TYPE:
            template.content_as_html = expected_html

        assert template.html == expected_html
