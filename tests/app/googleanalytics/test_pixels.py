from urllib.parse import quote_plus

from flask import current_app

from app.googleanalytics.pixels import build_ga_pixel_url


def test_build_ga_pixel_url_contains_expected_parameters(
    notify_api,
    sample_notification_model_with_organization,
    mock_email_client,
):
    img_src_url = build_ga_pixel_url(sample_notification_model_with_organization, mock_email_client)

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
        'ci=',
    ]

    assert all(parameter in img_src_url for parameter in all_expected_parameters)


def test_build_ga_pixel_url_is_escaped(
    notify_api,
    sample_notification_model_with_organization,
    mock_email_client,
):
    escaped_provider_name = quote_plus(mock_email_client.get_name())
    escaped_template_name = quote_plus(sample_notification_model_with_organization.template.name)
    escaped_service_name = quote_plus(sample_notification_model_with_organization.service.name)
    escaped_organization_name = quote_plus(sample_notification_model_with_organization.service.organisation.name)
    escaped_subject_name = quote_plus(sample_notification_model_with_organization.subject)

    img_src_url = build_ga_pixel_url(sample_notification_model_with_organization, mock_email_client)

    ga_tid = current_app.config['GOOGLE_ANALYTICS_TID']
    assert 'v=1' in img_src_url
    assert 't=event' in img_src_url
    assert f'tid={ga_tid}' in img_src_url
    assert f'cid={sample_notification_model_with_organization.id}' in img_src_url
    assert 'aip=1' in img_src_url
    assert 'ec=email' in img_src_url
    assert 'ea=open' in img_src_url
    assert f'el={escaped_template_name}' in img_src_url
    assert f'%2F{escaped_organization_name}' f'%2F{escaped_service_name}' f'%2F{escaped_template_name}' in img_src_url
    assert f'dt={escaped_subject_name}' in img_src_url
    assert f'cn={escaped_template_name}' in img_src_url
    assert f'cs={escaped_provider_name}' in img_src_url
    assert 'cm=email' in img_src_url
    assert f'ci={sample_notification_model_with_organization.template.id}' in img_src_url


def test_build_ga_pixel_url_without_organization(
    notify_api,
    sample_notification_model_with_organization,
    mock_email_client,
):
    sample_notification_model_with_organization.service.organisation = None

    img_src_url = build_ga_pixel_url(sample_notification_model_with_organization, mock_email_client)

    service_name = sample_notification_model_with_organization.service.name
    template_name = sample_notification_model_with_organization.template.name
    assert quote_plus(f'/email/vanotify/{service_name}/{template_name}') in img_src_url
