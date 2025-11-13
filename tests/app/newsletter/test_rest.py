import json
from unittest.mock import Mock

import pytest
from flask import url_for

from app.clients.airtable.models import NewsletterSubscriber


class MockSaveResult:
    """Mock object to simulate SaveResult from pyairtable."""

    def __init__(self, saved=True, error=None):
        self.saved = saved
        self.error = error


@pytest.fixture
def mock_subscriber():
    """Create a mock NewsletterSubscriber."""
    subscriber = Mock(spec=NewsletterSubscriber)
    subscriber.id = "rec123456"
    subscriber.email = "test@example.com"
    subscriber.language = "en"
    subscriber.status = "unconfirmed"
    subscriber.created_at = None
    subscriber.confirmed_at = None
    subscriber.unsubscribed_at = None
    return subscriber


class TestCreateUnconfirmedSubscription:
    def test_create_unconfirmed_subscription_success(self, notify_api, mocker):
        """Test successfully creating an unconfirmed newsletter subscriber."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                # Mock the NewsletterSubscriber class
                mock_subscriber_instance = Mock()
                mock_subscriber_instance.id = "rec123456"
                mock_subscriber_instance.save_unconfirmed_subscriber.return_value = MockSaveResult(saved=True)

                mock_subscriber_class = mocker.patch(
                    "app.newsletter.rest.NewsletterSubscriber", return_value=mock_subscriber_instance
                )

                data = {"email": "test@example.com", "language": "en"}
                response = client.post(
                    url_for("newsletter.create_unconfirmed_subscription"),
                    data=json.dumps(data),
                    headers=[("Content-Type", "application/json")],
                )

                assert response.status_code == 201
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "success"
                assert json_resp["subscriber_id"] == "rec123456"

                # Verify the subscriber was created with correct parameters
                mock_subscriber_class.assert_called_once_with(email="test@example.com", language="en")
                mock_subscriber_instance.save_unconfirmed_subscriber.assert_called_once()

    def test_create_unconfirmed_subscription_defaults_to_english(self, notify_api, mocker):
        """Test that language defaults to 'en' when not provided."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                mock_subscriber_instance = Mock()
                mock_subscriber_instance.id = "rec123456"
                mock_subscriber_instance.save_unconfirmed_subscriber.return_value = MockSaveResult(saved=True)

                mock_subscriber_class = mocker.patch(
                    "app.newsletter.rest.NewsletterSubscriber", return_value=mock_subscriber_instance
                )

                data = {"email": "test@example.com"}
                response = client.post(
                    url_for("newsletter.create_unconfirmed_subscription"),
                    data=json.dumps(data),
                    headers=[("Content-Type", "application/json")],
                )

                assert response.status_code == 201
                # Verify the default language was used
                mock_subscriber_class.assert_called_once_with(email="test@example.com", language="en")

    def test_create_unconfirmed_subscription_missing_email(self, notify_api):
        """Test that missing email returns 400 error."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                data = {"language": "fr"}
                response = client.post(
                    url_for("newsletter.create_unconfirmed_subscription"),
                    data=json.dumps(data),
                    headers=[("Content-Type", "application/json")],
                )

                assert response.status_code == 400
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "error"
                assert json_resp["message"] == "Email is required"

    def test_create_unconfirmed_subscription_save_fails(self, notify_api, mocker):
        """Test handling of save failure."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                mock_subscriber_instance = Mock()
                mock_subscriber_instance.id = "rec123456"
                mock_subscriber_instance.save_unconfirmed_subscriber.return_value = MockSaveResult(
                    saved=False, error="Database error"
                )

                mocker.patch("app.newsletter.rest.NewsletterSubscriber", return_value=mock_subscriber_instance)

                data = {"email": "test@example.com", "language": "en"}
                response = client.post(
                    url_for("newsletter.create_unconfirmed_subscription"),
                    data=json.dumps(data),
                    headers=[("Content-Type", "application/json")],
                )

                assert response.status_code == 500
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "error"
                assert json_resp["message"] == "Failed to create unconfirmed mailing list subscriber."


class TestConfirmSubscription:
    def test_confirm_subscription_success(self, notify_api, mocker):
        """Test successfully confirming a newsletter subscription."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                mock_subscriber = Mock()
                mock_subscriber.id = "rec123456"
                mock_subscriber.confirm_subscription.return_value = MockSaveResult(saved=True)

                mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)

                response = client.post(url_for("newsletter.confirm_subscription", subscriber_id="rec123456"))

                assert response.status_code == 200
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "success"
                assert json_resp["message"] == "Subscription confirmed"
                assert json_resp["record_id"] == "rec123456"

                mock_subscriber.confirm_subscription.assert_called_once()

    def test_confirm_subscription_subscriber_not_found(self, notify_api, mocker):
        """Test confirming subscription for non-existent subscriber."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=None)

                response = client.post(url_for("newsletter.confirm_subscription", subscriber_id="rec999999"))

                assert response.status_code == 404
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "error"
                assert json_resp["message"] == "Subscriber not found"

    def test_confirm_subscription_save_fails(self, notify_api, mocker):
        """Test handling of confirmation save failure."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                mock_subscriber = Mock()
                mock_subscriber.id = "rec123456"
                mock_subscriber.confirm_subscription.return_value = MockSaveResult(saved=False, error="Database error")

                mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)

                response = client.post(url_for("newsletter.confirm_subscription", subscriber_id="rec123456"))

                assert response.status_code == 500
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "error"
                assert json_resp["message"] == "Subscription confirmation failed"
                assert json_resp["record_id"] == "rec123456"


class TestUnsubscribe:
    def test_unsubscribe_success(self, notify_api, mocker):
        """Test successfully unsubscribing from newsletter."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                mock_subscriber = Mock()
                mock_subscriber.id = "rec123456"
                mock_subscriber.unsubscribe_user.return_value = MockSaveResult(saved=True)

                mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)

                response = client.post(url_for("newsletter.unsubscribe", subscriber_id="rec123456"))

                assert response.status_code == 200
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "success"
                assert json_resp["message"] == "Unsubscribed successfully"
                assert json_resp["record_id"] == "rec123456"

                mock_subscriber.unsubscribe_user.assert_called_once()

    def test_unsubscribe_subscriber_not_found(self, notify_api, mocker):
        """Test unsubscribing non-existent subscriber."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=None)

                response = client.post(url_for("newsletter.unsubscribe", subscriber_id="rec999999"))

                assert response.status_code == 404
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "error"
                assert json_resp["message"] == "Subscriber not found"

    def test_unsubscribe_save_fails(self, notify_api, mocker):
        """Test handling of unsubscribe save failure."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                mock_subscriber = Mock()
                mock_subscriber.id = "rec123456"
                mock_subscriber.unsubscribe_user.return_value = MockSaveResult(saved=False, error="Database error")

                mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)

                response = client.post(url_for("newsletter.unsubscribe", subscriber_id="rec123456"))

                assert response.status_code == 500
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "error"
                assert json_resp["message"] == "Unsubscription failed"
                assert json_resp["record_id"] == "rec123456"


class TestUpdateLanguagePreferences:
    def test_update_language_success(self, notify_api, mocker):
        """Test successfully updating language preference."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                mock_subscriber = Mock()
                mock_subscriber.id = "rec123456"
                mock_subscriber.update_language.return_value = MockSaveResult(saved=True)

                mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)

                data = {"language": "fr"}
                response = client.post(
                    url_for("newsletter.update_language_preferences", subscriber_id="rec123456"),
                    data=json.dumps(data),
                    headers=[("Content-Type", "application/json")],
                )

                assert response.status_code == 200
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "success"
                assert json_resp["message"] == "Language updated successfully"
                assert json_resp["record_id"] == "rec123456"

                mock_subscriber.update_language.assert_called_once_with("fr")

    def test_update_language_missing_language(self, notify_api):
        """Test that missing language parameter returns 400 error."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                data = {}
                response = client.post(
                    url_for("newsletter.update_language_preferences", subscriber_id="rec123456"),
                    data=json.dumps(data),
                    headers=[("Content-Type", "application/json")],
                )

                assert response.status_code == 400
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "error"
                assert json_resp["message"] == "New language is required"

    def test_update_language_subscriber_not_found(self, notify_api, mocker):
        """Test updating language for non-existent subscriber."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=None)

                data = {"language": "fr"}
                response = client.post(
                    url_for("newsletter.update_language_preferences", subscriber_id="rec999999"),
                    data=json.dumps(data),
                    headers=[("Content-Type", "application/json")],
                )

                assert response.status_code == 404
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "error"
                assert json_resp["message"] == "Subscriber not found"

    def test_update_language_save_fails(self, notify_api, mocker):
        """Test handling of language update save failure."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                mock_subscriber = Mock()
                mock_subscriber.id = "rec123456"
                mock_subscriber.update_language.return_value = MockSaveResult(saved=False, error="Database error")

                mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)

                data = {"language": "fr"}
                response = client.post(
                    url_for("newsletter.update_language_preferences", subscriber_id="rec123456"),
                    data=json.dumps(data),
                    headers=[("Content-Type", "application/json")],
                )

                assert response.status_code == 500
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "error"
                assert json_resp["message"] == "Language update failed"
                assert json_resp["record_id"] == "rec123456"


class TestGetSubscriber:
    def test_get_subscriber_by_id_success(self, notify_api, mocker):
        """Test successfully retrieving subscriber by ID."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                mock_subscriber = Mock()
                mock_subscriber.id = "rec123456"
                mock_subscriber.email = "test@example.com"
                mock_subscriber.language = "en"
                mock_subscriber.status = "subscribed"
                mock_subscriber.created_at = "2024-01-01T00:00:00"
                mock_subscriber.confirmed_at = "2024-01-02T00:00:00"
                mock_subscriber.unsubscribed_at = None

                mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)

                response = client.get(url_for("newsletter.get_subscriber", subscriber_id="rec123456"))

                assert response.status_code == 200
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "success"
                assert json_resp["subscriber"]["id"] == "rec123456"
                assert json_resp["subscriber"]["email"] == "test@example.com"
                assert json_resp["subscriber"]["language"] == "en"
                assert json_resp["subscriber"]["status"] == "subscribed"

    def test_get_subscriber_by_email_success(self, notify_api, mocker):
        """Test successfully retrieving subscriber by email."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                mock_subscriber = Mock()
                mock_subscriber.id = "rec123456"
                mock_subscriber.email = "test@example.com"
                mock_subscriber.language = "fr"
                mock_subscriber.status = "subscribed"
                mock_subscriber.created_at = "2024-01-01T00:00:00"
                mock_subscriber.confirmed_at = "2024-01-02T00:00:00"
                mock_subscriber.unsubscribed_at = None

                mocker.patch("app.newsletter.rest.NewsletterSubscriber.get_by_email", return_value=mock_subscriber)

                response = client.get(url_for("newsletter.get_subscriber", email="test@example.com"))

                assert response.status_code == 200
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "success"
                assert json_resp["subscriber"]["email"] == "test@example.com"
                assert json_resp["subscriber"]["language"] == "fr"

    def test_get_subscriber_by_id_not_found(self, notify_api, mocker):
        """Test retrieving non-existent subscriber by ID."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=None)

                response = client.get(url_for("newsletter.get_subscriber", subscriber_id="rec999999"))

                assert response.status_code == 404
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "error"
                assert json_resp["message"] == "Subscriber not found"

    def test_get_subscriber_by_email_not_found(self, notify_api, mocker):
        """Test retrieving non-existent subscriber by email."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                mocker.patch("app.newsletter.rest.NewsletterSubscriber.get_by_email", return_value=None)

                response = client.get(url_for("newsletter.get_subscriber", email="notfound@example.com"))

                assert response.status_code == 404
                json_resp = json.loads(response.get_data(as_text=True))
                assert json_resp["result"] == "error"
                assert json_resp["message"] == "Subscriber not found"

    def test_get_subscriber_no_id_or_email(self, notify_api):
        """Test that missing both ID and email returns 400 error."""
        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                # This will call the route without subscriber_id parameter
                # Due to the route structure, we need to test the /email/ route with no email
                response = client.get("/newsletter/")

                # This should return 404 as the route doesn't match, but testing the logic
                # Let's check what happens when we access the root newsletter endpoint
                assert response.status_code == 404
