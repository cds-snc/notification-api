"""Test endpoints for Google Analytics 4."""

from unittest.mock import patch

from flask import url_for


def test_it_get_ga4_valid_data(client, ga4_request_data, sample_notification):
    """
    A GET request with valid URL parameters should receive a 200 response and
    send image of a pixel.
    """
    notification = sample_notification()
    with patch('app.googleanalytics.ga4.post_to_ga4.delay') as mock_post_to_ga4:
        response = client.get(
            path=url_for('ga4.get_ga4', notification_id=notification.id),
        )
    assert response.status_code == 200, response.get_json()
    assert response.headers['Content-Type'].startswith('image/')
    assert 'ga4_pixel_tracking.png' in response.headers['Content-Disposition']
    assert mock_post_to_ga4.called
    assert mock_post_to_ga4.call_args[0] == (
        str(notification.id),
        'email_open',
        'vanotify',
        'email',
    )


def test_get_ga4_with_invalid_notification_id(client):
    """
    A GET request with an invalid notification ID should receive a 200 response and the pixel image
    without sending the GA4 request to celery.
    """
    with patch('app.googleanalytics.ga4.post_to_ga4.delay') as mock_post_to_ga4:
        response = client.get(
            path=url_for('ga4.get_ga4', notification_id='invalid-uuid4'),
        )
    assert response.status_code == 200
    assert not mock_post_to_ga4.called
    assert response.headers['Content-Type'].startswith('image/')
    assert 'ga4_pixel_tracking.png' in response.headers['Content-Disposition']
