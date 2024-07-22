"""Test endpoints for Google Analytics 4."""

from unittest.mock import patch

from flask import url_for


def test_it_get_ga4_valid_data(client, ga4_request_data):
    """
    A GET request with valid URL parameters should receive a 200 response and
    send image of a pixel.
    """
    with patch('app.googleanalytics.ga4.post_to_ga4.delay') as mock_post_to_ga4:
        response = client.get(
            path=url_for('ga4.get_ga4'),
            query_string=ga4_request_data,
        )
    assert response.status_code == 200, response.get_json()
    assert response.headers['Content-Type'].startswith('image/')
    assert 'ga4_pixel_tracking.png' in response.headers['Content-Disposition']
    assert mock_post_to_ga4.called
    assert mock_post_to_ga4.call_args[0] == (
        'e774d2a6-4946-41b5-841a-7ac6a42d178b',
        'hi',
        'e774d2a6-4946-41b5-841a-7ac6a42d178b',
        'e774d2a6-4946-41b5-841a-7ac6a42d178b',
        'test',
    )
    assert mock_post_to_ga4.call_args[1] == {
        'name': 'email_open',
        'source': 'vanotify',
        'medium': 'email',
    }


def test_it_get_ga4_invalid_data(client):
    """
    A GET request with invalid URL parameters should receive a 400 ("Bad Request") response.
    Test this by omitting all URL parameters.  Other tests validate the schema.
    """

    response = client.get(path=url_for('ga4.get_ga4'))
    assert response.status_code == 400, response.get_json()


def test_it_get_ga4_invalid_content(client, ga4_request_data):
    """
    A GET request with invalid content should receive a 400 ("Bad Request") response.
    Test this by changing the content to an invalid format.
    """

    ga4_request_data['content'] = 'invalid_content'

    response = client.get(
        path=url_for('ga4.get_ga4'),
        query_string=ga4_request_data,
    )

    assert response.status_code == 400, response.get_json()
