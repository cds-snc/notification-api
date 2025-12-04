from unittest.mock import Mock

import pytest
from requests import HTTPError, Response

from app.clients.airtable.models import NewsletterSubscriber


class MockSaveResult:
    """Mock object to simulate SaveResult from pyairtable."""

    def __init__(self, saved=True, error=None):
        self.saved = saved
        self.error = error


@pytest.fixture(scope="function")
def mock_subscriber(
    status="unconfirmed",
    language="en",
):
    subscriber = Mock(spec=NewsletterSubscriber)
    subscriber.id = "rec123456"
    subscriber.email = "test@example.com"
    subscriber.language = "en"
    subscriber.status = "unconfirmed"
    subscriber.created_at = None
    subscriber.confirmed_at = None
    subscriber.unsubscribed_at = None
    subscriber.has_resubscribed = False

    def _to_dict():
        return {
            "id": subscriber.id,
            "email": subscriber.email,
            "language": subscriber.language,
            "status": subscriber.status,
            "created_at": subscriber.created_at,
            "confirmed_at": subscriber.confirmed_at,
            "unsubscribed_at": subscriber.unsubscribed_at,
            "has_resubscribed": subscriber.has_resubscribed,
        }

    subscriber.to_dict = _to_dict()
    return subscriber


class TestCreateUnconfirmedSubscription:
    def test_create_unconfirmed_subscription_success(self, admin_request, mocker, mock_subscriber):
        mock_subscriber.save_unconfirmed_subscriber.return_value = MockSaveResult(saved=True)

        mock_subscriber_class = mocker.patch("app.newsletter.rest.NewsletterSubscriber", return_value=mock_subscriber)
        mock_send_email = mocker.patch("app.newsletter.rest.send_confirmation_email")
        mock_response = Response()
        mock_response.status_code = 404
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_email", side_effect=HTTPError(response=mock_response))

        data = {"email": "test@example.com", "language": "en"}
        response = admin_request.post("newsletter.create_unconfirmed_subscription", _data=data, _expected_status=201)

        assert response["result"] == "success"
        assert response["subscriber"] == mock_subscriber.to_dict
        mock_subscriber_class.assert_called_once_with(
            email=response["subscriber"]["email"], language=response["subscriber"]["language"]
        )
        mock_subscriber.save_unconfirmed_subscriber.assert_called_once()
        mock_send_email.assert_called_once_with(
            response["subscriber"]["id"], response["subscriber"]["email"], response["subscriber"]["language"]
        )

    def test_create_unconfirmed_subscription_defaults_to_english(self, admin_request, mocker, mock_subscriber):
        mock_subscriber.save_unconfirmed_subscriber.return_value = MockSaveResult(saved=True)

        mock_subscriber_class = mocker.patch("app.newsletter.rest.NewsletterSubscriber", return_value=mock_subscriber)
        mock_send_email = mocker.patch("app.newsletter.rest.send_confirmation_email")
        mock_response = Response()
        mock_response.status_code = 404
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_email", side_effect=HTTPError(response=mock_response))

        data = {"email": "test@example.com"}
        response = admin_request.post("newsletter.create_unconfirmed_subscription", _data=data, _expected_status=201)

        assert response["result"] == "success"
        mock_subscriber_class.assert_called_once_with(email="test@example.com", language="en")
        mock_send_email.assert_called_once_with("rec123456", "test@example.com", "en")

    def test_create_unconfirmed_subscription_missing_email(self, admin_request):
        data = {"language": "fr"}
        response = admin_request.post("newsletter.create_unconfirmed_subscription", _data=data, _expected_status=400)
        assert response["result"] == "error"
        assert response["message"] == "Email is required"

    def test_create_unconfirmed_subscription_save_fails(self, admin_request, mocker, mock_subscriber):
        mock_subscriber.save_unconfirmed_subscriber.return_value = MockSaveResult(saved=False, error="Database error")

        mocker.patch("app.newsletter.rest.NewsletterSubscriber", return_value=mock_subscriber)
        mock_send_email = mocker.patch("app.newsletter.rest.send_confirmation_email")
        mock_response = Response()
        mock_response.status_code = 404
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_email", side_effect=HTTPError(response=mock_response))

        data = {"email": "test@example.com", "language": "en"}
        response = admin_request.post("newsletter.create_unconfirmed_subscription", _data=data, _expected_status=500)
        assert response["result"] == "error"
        assert response["message"] == "Failed to create unconfirmed mailing list subscriber."
        # Email should not be sent if save fails
        mock_send_email.assert_not_called()

    def test_create_unconfirmed_subscription_existing_subscriber(self, admin_request, mocker, mock_subscriber):
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_email", return_value=mock_subscriber)
        mock_send_email = mocker.patch("app.newsletter.rest.send_confirmation_email")

        data = {"email": "test@example.com", "language": "en"}
        response = admin_request.post("newsletter.create_unconfirmed_subscription", _data=data, _expected_status=200)

        assert response["result"] == "success"
        assert response["message"] == "A subscriber with this email already exists"
        assert response["subscriber"] == mock_subscriber.to_dict
        # Confirmation email should be resent for existing subscriber
        mock_send_email.assert_called_once_with("rec123456", "test@example.com", "en")

    def test_create_unconfirmed_subscription_api_error(self, admin_request, mocker):
        mock_response = Response()
        mock_response.status_code = 500
        mock_response._content = b"Internal Server Error"
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_email", side_effect=HTTPError(response=mock_response))

        data = {"email": "test@example.com", "language": "en"}
        response = admin_request.post("newsletter.create_unconfirmed_subscription", _data=data, _expected_status=500)

        assert response["result"] == "error"
        assert "Error fetching existing subscriber" in response["message"]


class TestConfirmSubscription:
    def test_confirm_subscription_success(self, admin_request, mock_subscriber, mocker):
        mock_subscriber.confirm_subscription.return_value = MockSaveResult(saved=True)

        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)

        response = admin_request.get("newsletter.confirm_subscription", subscriber_id=mock_subscriber.id, _expected_status=200)

        assert response["result"] == "success"
        assert response["message"] == "Subscription confirmed"
        assert response["subscriber"] == mock_subscriber.to_dict

        mock_subscriber.confirm_subscription.assert_called_once()

    def test_confirm_subscription_already_confirmed(self, admin_request, mocker, mock_subscriber):
        mock_subscriber.status = NewsletterSubscriber.Statuses.SUBSCRIBED.value
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)
        response = admin_request.get("newsletter.confirm_subscription", subscriber_id=mock_subscriber.id, _expected_status=200)
        assert response["result"] == "success"
        assert response["message"] == "Subscription already confirmed"
        assert response["subscriber"] == mock_subscriber.to_dict

    def test_confirm_subscription_resubscribe_success(self, admin_request, mocker, mock_subscriber):
        mock_subscriber.status = NewsletterSubscriber.Statuses.UNSUBSCRIBED.value
        mock_subscriber.confirm_subscription.return_value = MockSaveResult(saved=True)

        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)

        response = admin_request.get("newsletter.confirm_subscription", subscriber_id=mock_subscriber.id, _expected_status=200)

        assert response["result"] == "success"
        assert response["message"] == "Subscription confirmed"
        assert response["subscriber"] == mock_subscriber.to_dict

        # Verify that confirm_subscription was called with has_resubscribed=True
        mock_subscriber.confirm_subscription.assert_called_once_with(has_resubscribed=True)

    def test_confirm_subscription_subscriber_not_found(self, admin_request, mocker):
        mock_response = Response()
        mock_response.status_code = 404
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", side_effect=HTTPError(response=mock_response))

        response = admin_request.get("newsletter.confirm_subscription", subscriber_id="rec999999", _expected_status=404)

        assert response["result"] == "error"
        assert response["message"] == "Subscriber not found"

    def test_confirm_subscription_save_fails(self, admin_request, mocker):
        mock_subscriber = Mock()
        mock_subscriber.id = "rec123456"
        mock_subscriber.confirm_subscription.return_value = MockSaveResult(saved=False, error="Database error")

        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)

        response = admin_request.get("newsletter.confirm_subscription", subscriber_id="rec123456", _expected_status=500)

        assert response["result"] == "error"
        assert response["message"] == "Subscription confirmation failed"


class TestUnsubscribe:
    def test_unsubscribe_success(self, admin_request, mocker, mock_subscriber):
        mock_subscriber.unsubscribe_user.return_value = MockSaveResult(saved=True)

        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)

        response = admin_request.get("newsletter.unsubscribe", subscriber_id=mock_subscriber.id, _expected_status=200)

        assert response["result"] == "success"
        assert response["message"] == "Unsubscribed successfully"
        assert response["subscriber"] == mock_subscriber.to_dict

        mock_subscriber.unsubscribe_user.assert_called_once()

    def test_unsubscribe_already_unsubscribed(self, admin_request, mocker, mock_subscriber):
        mock_subscriber.status = NewsletterSubscriber.Statuses.UNSUBSCRIBED.value
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)
        response = admin_request.get("newsletter.unsubscribe", subscriber_id="rec123456", _expected_status=200)
        assert response["result"] == "success"
        assert response["message"] == "Subscriber has already unsubscribed"
        assert response["subscriber"] == mock_subscriber.to_dict

    def test_unsubscribe_subscriber_not_found(self, admin_request, mocker):
        mock_response = Response()
        mock_response.status_code = 404
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", side_effect=HTTPError(response=mock_response))

        response = admin_request.get("newsletter.unsubscribe", subscriber_id="rec999999", _expected_status=404)

        assert response["result"] == "error"
        assert response["message"] == "Subscriber not found"

    def test_unsubscribe_save_fails(self, admin_request, mocker):
        mock_subscriber = Mock()
        mock_subscriber.id = "rec123456"
        mock_subscriber.unsubscribe_user.return_value = MockSaveResult(saved=False, error="Database error")

        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)

        response = admin_request.get("newsletter.unsubscribe", subscriber_id="rec123456", _expected_status=500)

        assert response["result"] == "error"
        assert response["message"] == "Unsubscription failed"


class TestUpdateLanguagePreferences:
    def test_update_language_success(self, admin_request, mocker, mock_subscriber):
        mock_subscriber.update_language.return_value = MockSaveResult(saved=True)
        mock_subscriber.language = "fr"
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)

        data = {"language": "fr"}
        response = admin_request.post(
            "newsletter.update_language_preferences",
            subscriber_id=mock_subscriber.id,
            _data=data,
            _expected_status=200,
        )

        assert response["result"] == "success"
        assert response["message"] == "Language updated successfully"
        assert response["subscriber"] == mock_subscriber.to_dict

        mock_subscriber.update_language.assert_called_once_with("fr")

    def test_update_language_missing_language(self, admin_request):
        data = {}
        response = admin_request.post(
            "newsletter.update_language_preferences", subscriber_id="rec123456", _data=data, _expected_status=400
        )

        assert response["result"] == "error"
        assert response["message"] == "New language is required"

    def test_update_language_subscriber_not_found(self, admin_request, mocker):
        mock_response = Response()
        mock_response.status_code = 404
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", side_effect=HTTPError(response=mock_response))

        data = {"language": "fr"}
        response = admin_request.post(
            "newsletter.update_language_preferences", subscriber_id="rec999999", _data=data, _expected_status=404
        )

        assert response["result"] == "error"
        assert response["message"] == "Subscriber not found"

    def test_update_language_save_fails(self, admin_request, mocker):
        mock_subscriber = Mock()
        mock_subscriber.id = "rec123456"
        mock_subscriber.update_language.return_value = MockSaveResult(saved=False, error="Database error")

        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)

        data = {"language": "fr"}
        response = admin_request.post(
            "newsletter.update_language_preferences", subscriber_id="rec123456", _data=data, _expected_status=500
        )

        assert response["result"] == "error"
        assert response["message"] == "Language update failed"


class TestSendLatestNewsletter:
    def test_send_latest_newsletter_success(self, admin_request, mocker, mock_subscriber):
        mock_subscriber.status = NewsletterSubscriber.Statuses.SUBSCRIBED.value
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)
        mock_send_newsletter = mocker.patch("app.newsletter.rest._send_latest_newsletter")

        response = admin_request.get("newsletter.send_latest_newsletter", subscriber_id="rec123456", _expected_status=200)

        assert response["result"] == "success"
        assert response["subscriber"] == mock_subscriber.to_dict
        mock_send_newsletter.assert_called_once_with("rec123456", "test@example.com", "en")

    def test_send_latest_newsletter_subscriber_already_subscribed(self, admin_request, mocker, mock_subscriber):
        mock_subscriber.status = NewsletterSubscriber.Statuses.SUBSCRIBED.value
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)
        mock_send_newsletter = mocker.patch("app.newsletter.rest._send_latest_newsletter")

        response = admin_request.get("newsletter.send_latest_newsletter", subscriber_id="rec123456", _expected_status=400)

        assert response["result"] == "error"
        assert "cannot receive newsletters" in response["message"]
        mock_send_newsletter.assert_not_called()

    def test_send_latest_newsletter_subscriber_not_found(self, admin_request, mocker):
        mock_response = Response()
        mock_response.status_code = 404
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", side_effect=HTTPError(response=mock_response))

        response = admin_request.get("newsletter.send_latest_newsletter", subscriber_id="rec999999", _expected_status=404)

        assert response["result"] == "error"
        assert response["message"] == "Subscriber not found"

    def test_send_latest_newsletter_api_error(self, admin_request, mocker):
        mock_response = Response()
        mock_response.status_code = 500
        mock_response._content = b"Internal Server Error"
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", side_effect=HTTPError(response=mock_response))

        response = admin_request.get("newsletter.send_latest_newsletter", subscriber_id="rec123456", _expected_status=500)

        assert response["result"] == "error"
        assert "Failed to fetch subscriber" in response["message"]


class TestGetSubscriber:
    def test_get_subscriber_by_id_success(self, admin_request, mocker, mock_subscriber):
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", return_value=mock_subscriber)

        response = admin_request.get("newsletter.get_subscriber", subscriber_id="rec123456")

        assert response["result"] == "success"
        assert response["subscriber"]["id"] == "rec123456"
        assert response["subscriber"]["email"] == "test@example.com"
        assert response["subscriber"]["language"] == "en"
        assert response["subscriber"]["status"] == "unconfirmed"

    def test_get_subscriber_by_email_success(self, admin_request, mocker, mock_subscriber):
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_email", return_value=mock_subscriber)

        response = admin_request.get("newsletter.get_subscriber", email="test@example.com")

        assert response["result"] == "success"
        assert response["subscriber"]["email"] == "test@example.com"
        assert response["subscriber"]["language"] == "en"

    def test_get_subscriber_by_id_not_found(self, admin_request, mocker):
        mock_response = Response()
        mock_response.status_code = 404
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_id", side_effect=HTTPError(response=mock_response))

        response = admin_request.get("newsletter.get_subscriber", subscriber_id="rec999999", _expected_status=404)

        assert response["result"] == "error"
        assert response["message"] == "Subscriber not found"

    def test_get_subscriber_by_email_not_found(self, admin_request, mocker):
        mock_response = Response()
        mock_response.status_code = 404
        mocker.patch("app.newsletter.rest.NewsletterSubscriber.from_email", side_effect=HTTPError(response=mock_response))

        response = admin_request.get("newsletter.get_subscriber", email="notfound@example.com", _expected_status=404)

        assert response["result"] == "error"
        assert response["message"] == "Subscriber not found"

    def test_get_subscriber_no_id_or_email(self, admin_request):
        response = admin_request.get("newsletter.get_subscriber", _expected_status=400)

        assert response["result"] == "error"
        assert response["message"] == "Subscriber ID or email is required"
