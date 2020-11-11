import app.googleanalytics.pixels as gapixels
import urllib
from flask import current_app


def test_build_ga_pixel_url_contains_expected_parameters(
        sample_notification_model_with_organization,
        mock_email_client
):
    img_src_url = gapixels.build_ga_pixel_url(sample_notification_model_with_organization, mock_email_client)

    assert img_src_url is not None

    all_expected_parameters = [
        't=',
        'tid=',
        'cid=',
        'aip=',
        'ec=',
        'ea=',
        'el=',
        'dp=',
        'dt=',
        'cn=',
        'cs=',
        'cm=',
        'ci='
    ]

    assert all(parameter in img_src_url for parameter in all_expected_parameters)


def test_build_ga_pixel_url_is_escaped(sample_notification_model_with_organization, mock_email_client):
    escaped_provider_name = urllib.parse.quote_plus(mock_email_client.get_name())
    escaped_template_name = urllib.parse.quote_plus(sample_notification_model_with_organization.template.name)
    escaped_service_name = urllib.parse.quote_plus(sample_notification_model_with_organization.service.name)
    escaped_organization_name = urllib.parse.quote_plus(
        sample_notification_model_with_organization.service.organisation.name
    )
    escaped_subject_name = urllib.parse.quote_plus(sample_notification_model_with_organization.subject)

    img_src_url = gapixels.build_ga_pixel_url(sample_notification_model_with_organization, mock_email_client)

    ga_tid = current_app.config['GOOGLE_ANALYTICS_TID']
    assert 'v=1' in img_src_url
    assert 't=event' in img_src_url
    assert f"tid={ga_tid}" in img_src_url
    assert f"cid={sample_notification_model_with_organization.id}" in img_src_url
    assert 'aip=1' in img_src_url
    assert 'ec=email' in img_src_url
    assert 'ea=open' in img_src_url
    assert f"el={escaped_template_name}" in img_src_url
    assert \
        f"%2F{escaped_organization_name}" \
        f"%2F{escaped_service_name}" \
        f"%2F{escaped_template_name}" in img_src_url
    assert f"dt={escaped_subject_name}" in img_src_url
    assert f"cn={escaped_template_name}" in img_src_url
    assert f"cs={escaped_provider_name}" in img_src_url
    assert f"cm=email" in img_src_url
    assert f"ci={sample_notification_model_with_organization.template.id}" in img_src_url
