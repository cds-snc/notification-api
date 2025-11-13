from flask import Blueprint, current_app, jsonify, request

from app.clients.airtable.models import NewsletterSubscriber
from app.errors import register_errors

newsletter_blueprint = Blueprint("newsletter", __name__, url_prefix="/newsletter")
register_errors(newsletter_blueprint)


@newsletter_blueprint.route("/unconfirmed-subscriber", methods=["POST"])
def create_unconfirmed_subscription():
    """Endpoint to create an unconfirmed newsletter subscriber."""
    data = request.get_json()
    email = data.get("email")
    language = data.get("language", "en")

    if not email:
        return jsonify(result="error", message="Email is required"), 400

    # Create a new unconfirmed subscriber
    subscriber = NewsletterSubscriber(email=email, language=language)
    result = subscriber.save_unconfirmed_subscriber()

    # Check if the save operation succeeded
    if not result.saved:
        current_app.logger.error(f"Failed to create unconfirmed mailing list subscriber: {result.error}")
        return jsonify(result="error", message="Failed to create unconfirmed mailing list subscriber."), 500

    return jsonify(result="success", subscriber_id=subscriber.id), 201


@newsletter_blueprint.route("/confirm/<subscriber_id>", methods=["GET"])
def confirm_subscription(subscriber_id):
    """Endpoint to confirm newsletter subscription."""
    subscriber = NewsletterSubscriber.from_id(record_id=subscriber_id)

    if not subscriber:
        return jsonify(result="error", message="Subscriber not found"), 404

    result = subscriber.confirm_subscription()

    if not result.saved:
        current_app.logger.error("Error confirming newsletter subscription: ")
        return jsonify(result="error", message="Subscription confirmation failed", record_id=subscriber.id), 500

    return jsonify(result="success", message="Subscription confirmed", record_id=subscriber.id), 200


@newsletter_blueprint.route("/unsubscribe/<subscriber_id>", methods=["GET"])
def unsubscribe(subscriber_id):
    """Endpoint to unsubscribe from the newsletter."""
    subscriber = NewsletterSubscriber.from_id(subscriber_id)

    if not subscriber:
        return jsonify(result="error", message="Subscriber not found"), 404

    result = subscriber.unsubscribe_user()

    if not result.saved:
        current_app.logger.error(f"Failed to unsubscribe newsletter subscriber: {subscriber.id}")
        return jsonify(result="error", message="Unsubscription failed", record_id=subscriber.id), 500

    return jsonify(result="success", message="Unsubscribed successfully", record_id=subscriber.id), 200


@newsletter_blueprint.route("/update-language/<subscriber_id>", methods=["POST"])
def update_language_preferences(subscriber_id):
    """Endpoint to update language preferences for a subscriber."""
    data = request.get_json()
    new_language = data.get("language")

    if not new_language:
        return jsonify(result="error", message="New language is required"), 400

    subscriber = NewsletterSubscriber.from_id(subscriber_id)

    if not subscriber:
        return jsonify(result="error", message="Subscriber not found"), 404

    result = subscriber.update_language(new_language)

    if not result.saved:
        current_app.logger.error(f"Failed to update language preferences for newsletter subscriber: {subscriber.id}")
        return jsonify(result="error", message="Language update failed", record_id=subscriber.id), 500

    return jsonify(result="success", message="Language updated successfully", record_id=subscriber.id), 200


@newsletter_blueprint.route("/find-subscriber", methods=["GET"])
def get_subscriber():
    """Endpoint to retrieve subscriber information by ID or email."""
    data = request.get_json()
    subscriber_id = data.get("subscriber_id", None)
    email = data.get("email", None)

    if subscriber_id:
        subscriber = NewsletterSubscriber.from_id(subscriber_id)
    elif email:
        subscriber = NewsletterSubscriber.from_email(email)
    else:
        return jsonify(result="error", message="Subscriber ID or email is required"), 400

    if not subscriber:
        return jsonify(result="error", message="Subscriber not found"), 404

    subscriber_data = {
        "id": subscriber.id,
        "email": subscriber.email,
        "language": subscriber.language,
        "status": subscriber.status,
        "created_at": subscriber.created_at,
        "confirmed_at": subscriber.confirmed_at,
        "unsubscribed_at": subscriber.unsubscribed_at,
    }

    return jsonify(result="success", subscriber=subscriber_data), 200
