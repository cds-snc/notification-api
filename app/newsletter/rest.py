from flask import Blueprint, current_app, jsonify, request

from app.clients.airtable.models import NewsletterSubscriber
from app.errors import InvalidRequest, register_errors

newsletter_blueprint = Blueprint("newsletter", __name__, url_prefix="/newsletter")
register_errors(newsletter_blueprint)


@newsletter_blueprint.route("/unconfirmed-subscriber", methods=["POST"])
def create_unconfirmed_subscription():
    """Endpoint to create an unconfirmed newsletter subscriber."""
    data = request.get_json()
    email = data.get("email")
    language = data.get("language", "en")

    if not email:
        raise InvalidRequest("Email is required", status_code=400)

    # Create a new unconfirmed subscriber
    subscriber = NewsletterSubscriber(email=email, language=language)
    result = subscriber.save_unconfirmed_subscriber()

    # Check if the save operation succeeded
    if not result.saved:
        current_app.logger.error("Failed to create unconfirmed mailing list subscriber. Record was not saved")
        raise InvalidRequest("Failed to create unconfirmed mailing list subscriber.", status_code=500)

    return jsonify(result="success", subscriber_id=subscriber.id), 201


@newsletter_blueprint.route("/confirm/<subscriber_id>", methods=["POST"])
def confirm_subscription(subscriber_id):
    """Endpoint to confirm newsletter subscription."""
    subscriber = NewsletterSubscriber.from_id(record_id=subscriber_id)

    if not subscriber:
        raise InvalidRequest("Subscriber not found", status_code=404)

    result = subscriber.confirm_subscription()

    if not result.saved:
        current_app.logger.error(
            f"Failed to confirm newsletter subscription for subscriber_id: {subscriber.id}. Record was not saved"
        )
        raise InvalidRequest("Subscription confirmation failed", status_code=500)

    return jsonify(result="success", message="Subscription confirmed", subscriber_id=subscriber.id), 200


@newsletter_blueprint.route("/unsubscribe/<subscriber_id>", methods=["POST"])
def unsubscribe(subscriber_id):
    """Endpoint to unsubscribe from the newsletter."""
    subscriber = NewsletterSubscriber.from_id(subscriber_id)

    if not subscriber:
        raise InvalidRequest("Subscriber not found", status_code=404)

    result = subscriber.unsubscribe_user()

    if not result.saved:
        current_app.logger.error(f"Failed to unsubscribe newsletter subscriber: {subscriber.id}. Record was not saved")
        raise InvalidRequest("Unsubscription failed", status_code=500)

    return jsonify(result="success", message="Unsubscribed successfully", subscriber_id=subscriber.id), 200


@newsletter_blueprint.route("/update-language/<subscriber_id>", methods=["POST"])
def update_language_preferences(subscriber_id):
    """Endpoint to update language preferences for a subscriber."""
    data = request.get_json()
    new_language = data.get("language")

    if not new_language:
        raise InvalidRequest("New language is required", status_code=400)

    subscriber = NewsletterSubscriber.from_id(subscriber_id)

    if not subscriber:
        raise InvalidRequest("Subscriber not found", status_code=404)

    result = subscriber.update_language(new_language)

    if not result.saved:
        current_app.logger.error(
            f"Failed to update language preferences for newsletter subscriber: {subscriber.id}. Record was not saved"
        )
        raise InvalidRequest("Language update failed", status_code=500)

    return jsonify(result="success", message="Language updated successfully", subscriber_id=subscriber.id), 200


@newsletter_blueprint.route("/resubscribe/<subscriber_id>", methods=["POST"])
def reactivate_subscription(subscriber_id):
    """Endpoint to reactivate a newsletter subscription."""
    data = request.get_json()
    language = data.get("language")

    if not language:
        raise InvalidRequest("Language is required to resubscribe", status_code=400)

    subscriber = NewsletterSubscriber.from_id(subscriber_id)

    if not subscriber:
        raise InvalidRequest("Subscriber not found", status_code=404)

    result = subscriber.reactivate_subscription(language)

    if not result.saved:
        current_app.logger.error(
            f"Failed to reactivate newsletter subscription for subscriber: {subscriber.id}. Record was not saved"
        )
        raise InvalidRequest("Resubscription failed", status_code=500)

    return jsonify(result="success", message="Resubscribed successfully", subscriber_id=subscriber.id), 200


@newsletter_blueprint.route("/find-subscriber", methods=["GET"])
def get_subscriber():
    """Endpoint to retrieve subscriber information by ID or email."""
    subscriber_id = request.args.get("subscriber_id")
    email = request.args.get("email")

    if not subscriber_id and not email:
        raise InvalidRequest("Subscriber ID or email is required", status_code=400)

    if subscriber_id:
        subscriber = NewsletterSubscriber.from_id(subscriber_id)
    elif email:
        subscriber = NewsletterSubscriber.from_email(email)

    if not subscriber:
        raise InvalidRequest("Subscriber not found", status_code=404)

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
