from flask import Blueprint, current_app, jsonify, request

from app.clients.airtable.models import NewsletterSubscriber
from app.config import QueueNames
from app.dao.templates_dao import dao_get_template_by_id
from app.errors import InvalidRequest, register_errors
from app.models import EMAIL_TYPE, KEY_TYPE_NORMAL, Service
from app.notifications.process_notifications import persist_notification, send_notification_to_queue

newsletter_blueprint = Blueprint("newsletter", __name__, url_prefix="/newsletter")
register_errors(newsletter_blueprint)


@newsletter_blueprint.route("/unconfirmed-subscriber", methods=["POST"])
def create_unconfirmed_subscription():
    data = request.get_json()
    email = data.get("email")
    language = data.get("language", "en")

    if not email:
        raise InvalidRequest("Email is required", status_code=400)

    # Check if a subscriber with the given email already exists
    existing_subscriber = NewsletterSubscriber.from_email(email)
    if existing_subscriber:
        current_app.logger.warning("A Subscriber by this email already exists, re-sending confirmation email.")
        send_confirmation_email(existing_subscriber.id, existing_subscriber.email, existing_subscriber.language)
        return jsonify(
            result="success", message="A subscriber with this email already exists", subscriber=existing_subscriber.to_dict
        ), 200

    # Create a new unconfirmed subscriber
    subscriber = NewsletterSubscriber(email=email, language=language)
    result = subscriber.save_unconfirmed_subscriber()

    # Check if the save operation succeeded
    if not result.saved:
        current_app.logger.error("Failed to create unconfirmed mailing list subscriber. Record was not saved")
        raise InvalidRequest("Failed to create unconfirmed mailing list subscriber.", status_code=500)

    send_confirmation_email(subscriber.id, subscriber.email, subscriber.language)

    return jsonify(result="success", subscriber=subscriber.to_dict), 201


@newsletter_blueprint.route("/confirm/<subscriber_id>", methods=["GET"])
def confirm_subscription(subscriber_id):
    subscriber = NewsletterSubscriber.from_id(record_id=subscriber_id)

    if not subscriber:
        raise InvalidRequest("Subscriber not found", status_code=404)

    if subscriber.status == NewsletterSubscriber.Statuses.SUBSCRIBED.value:
        return jsonify(result="success", message="Subscription already confirmed", subscriber=subscriber.to_dict), 200

    result = subscriber.confirm_subscription()

    if not result.saved:
        current_app.logger.error(
            f"Failed to confirm newsletter subscription for subscriber_id: {subscriber.id}. Record was not saved"
        )
        raise InvalidRequest("Subscription confirmation failed", status_code=500)

    return jsonify(result="success", message="Subscription confirmed", subscriber=subscriber.to_dict), 200


@newsletter_blueprint.route("/unsubscribe/<subscriber_id>", methods=["GET"])
def unsubscribe(subscriber_id):
    subscriber = NewsletterSubscriber.from_id(subscriber_id)

    if not subscriber:
        raise InvalidRequest("Subscriber not found", status_code=404)

    if subscriber.status == NewsletterSubscriber.Statuses.UNSUBSCRIBED.value:
        return jsonify(result="success", message="Subscriber has already unsubscribed", subscriber=subscriber.to_dict), 200

    result = subscriber.unsubscribe_user()

    if not result.saved:
        current_app.logger.error(f"Failed to unsubscribe newsletter subscriber: {subscriber.id}. Record was not saved")
        raise InvalidRequest("Unsubscription failed", status_code=500)

    return jsonify(result="success", message="Unsubscribed successfully", subscriber=subscriber.to_dict), 200


@newsletter_blueprint.route("/update-language/<subscriber_id>", methods=["POST"])
def update_language_preferences(subscriber_id):
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

    return jsonify(result="success", message="Language updated successfully", subscriber=subscriber.to_dict), 200


@newsletter_blueprint.route("/resubscribe/<subscriber_id>", methods=["POST"])
def reactivate_subscription(subscriber_id):
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

    return jsonify(result="success", message="Resubscribed successfully", subscriber=subscriber.to_dict), 200


@newsletter_blueprint.route("/find-subscriber", methods=["GET"])
def get_subscriber():
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

    return jsonify(result="success", subscriber=subscriber.to_dict), 200


def send_confirmation_email(subscriber_id, recipient_email, language):
    template_id = (
        current_app.config["NEWSLETTER_CONFIRMATION_EMAIL_TEMPLATE_ID_EN"]
        if language == "en"
        else current_app.config["NEWSLETTER_CONFIRMATION_EMAIL_TEMPLATE_ID_FR"]
    )
    template = dao_get_template_by_id(template_id)
    service = Service.query.get(current_app.config["NOTIFY_SERVICE_ID"])

    if current_app.config["NOTIFY_ENVIRONMENT"] == "production":
        from notifications_utils.url_safe_token import generate_token

        token = generate_token(subscriber_id, current_app.config["SECRET_KEY"])
        # TODO: update this URL when we know for sure what the admin endpoint will be
        url = f"{current_app.config["ADMIN_BASE_URL"]}/newsletter-subscription/confirm/{token}"
    else:
        url = f"{current_app.config["ADMIN_BASE_URL"]}/newsletter/confirm/{subscriber_id}"

    saved_notification = persist_notification(
        template_id=template_id,
        template_version=template.version,
        recipient=recipient_email,
        service=service,
        personalisation={"confirmation_link": url},
        notification_type=EMAIL_TYPE,
        api_key_id=None,
        key_type=KEY_TYPE_NORMAL,
    )

    send_notification_to_queue(saved_notification, False, queue=QueueNames.NOTIFY)
