"""Test endpoints for Google Analytics 4."""

from flask import url_for


def test_it_get_ga4_valid_data(client, ga4_request_data):
    """
    A GET request with valid URL parameters should receive a 200 response and
    send image of a pixel.
    """

    response = client.get(
        path=url_for('ga4.get_ga4'),
        query_string=ga4_request_data,
    )

    assert response.status_code == 200, response.get_json()
    assert response.headers['Content-Type'].startswith('image/')
    assert 'ga4_pixel_tracking.png' in response.headers['Content-Disposition']


def test_it_get_ga4_invalid_data(client):
    """
    A GET request with invalid URL parameters should receive a 400 ("Bad Request") response.
    Test this by omitting all URL parameters.  Other tests validate the schema.
    """

    response = client.get(path=url_for('ga4.get_ga4'))
    assert response.status_code == 400, response.get_json()
