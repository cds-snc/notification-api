from flask import Blueprint, current_app, jsonify, request
from requests import HTTPError

from app.clients.airtable.models import GrowthNewsletterSubscriber, LatestNewsletterTemplate, NewsletterSubscriber
from app.config import QueueNames
from app.dao.templates_dao import dao_get_template_by_id
from app.errors import InvalidRequest, register_errors
from app.models import EMAIL_TYPE, KEY_TYPE_NORMAL, Service
from app.notifications.process_notifications import persist_notification, send_notification_to_queue

newsletter_blueprint = Blueprint("newsletter", __name__, url_prefix="/newsletter")
register_errors(newsletter_blueprint)

NEWSLETTER_AIRTABLE_WRITE_MAX_ATTEMPTS = 3


@newsletter_blueprint.route("/unconfirmed-subscriber", methods=["POST"])
def create_unconfirmed_subscription():
    data = request.get_json()
    email = data.get("email")
    language = data.get("language", "en")

    if not email:
        raise InvalidRequest("Email is required", status_code=400)

    # Check if a subscriber with the given email already exists
    try:
        existing_subscriber = NewsletterSubscriber.from_email(email)

        # Update language preference in case it has changed
        existing_subscriber.language = language
        _save_newsletter_with_retry(
            existing_subscriber.save,
            "Failed to create unconfirmed mailing list subscriber.",
            f"Failed to update existing newsletter subscriber for email: {email}. Record was not saved",
        )
        _sync_growth_subscriber_best_effort(existing_subscriber)

        current_app.logger.warning("A Subscriber by this email already exists, re-sending confirmation email.")
        send_confirmation_email(existing_subscriber.id, existing_subscriber.email, language)
        return jsonify(
            result="success", message="A subscriber with this email already exists", subscriber=existing_subscriber.to_dict
        ), 200
    except HTTPError as e:
        # If we didn't find a subscriber, we can proceed to create one
        if e.response.status_code != 404:
            raise InvalidRequest(f"Error fetching existing subscriber: {e.response.text}", status_code=e.response.status_code)

    # Create a new unconfirmed subscriber
    subscriber = NewsletterSubscriber(email=email, language=language)
    _save_newsletter_with_retry(
        subscriber.save_unconfirmed_subscriber,
        "Failed to create unconfirmed mailing list subscriber.",
        "Failed to create unconfirmed mailing list subscriber. Record was not saved",
    )
    _sync_growth_subscriber_best_effort(subscriber)

    send_confirmation_email(subscriber.id, subscriber.email, subscriber.language)

    return jsonify(result="success", subscriber=subscriber.to_dict), 201


@newsletter_blueprint.route("/confirm/<subscriber_id>", methods=["GET"])
def confirm_subscription(subscriber_id):
    try:
        subscriber = NewsletterSubscriber.from_id(record_id=subscriber_id)
    except HTTPError as e:
        if e.response.status_code == 404:
            raise InvalidRequest("Subscriber not found", status_code=404)
        raise InvalidRequest(f"Failed to fetch subscriber: {e.response.text}", status_code=e.response.status_code)

    # If already subscribed then return success
    if subscriber.status == NewsletterSubscriber.Statuses.SUBSCRIBED.value:
        return jsonify(result="success", message="Subscription already confirmed", subscriber=subscriber.to_dict), 200
    elif subscriber.status == NewsletterSubscriber.Statuses.UNSUBSCRIBED.value:
        _save_newsletter_with_retry(
            lambda: subscriber.confirm_subscription(has_resubscribed=True),
            "Subscription confirmation failed",
            f"Failed to confirm newsletter subscription for subscriber_id: {subscriber.id}. Record was not saved",
        )
    else:
        _save_newsletter_with_retry(
            subscriber.confirm_subscription,
            "Subscription confirmation failed",
            f"Failed to confirm newsletter subscription for subscriber_id: {subscriber.id}. Record was not saved",
        )
    _sync_growth_subscriber_best_effort(subscriber)

    return jsonify(result="success", message="Subscription confirmed", subscriber=subscriber.to_dict), 200


@newsletter_blueprint.route("/unsubscribe/<subscriber_id>", methods=["GET"])
def unsubscribe(subscriber_id):
    try:
        subscriber = NewsletterSubscriber.from_id(record_id=subscriber_id)
    except HTTPError as e:
        if e.response.status_code == 404:
            raise InvalidRequest("Subscriber not found", status_code=404)
        raise InvalidRequest(f"Failed to fetch subscriber: {e.response.text}", status_code=e.response.status_code)

    # If already unsubscribed then return success
    if subscriber.status == NewsletterSubscriber.Statuses.UNSUBSCRIBED.value:
        return jsonify(result="success", message="Subscriber has already unsubscribed", subscriber=subscriber.to_dict), 200

    _save_newsletter_with_retry(
        subscriber.unsubscribe_user,
        "Unsubscription failed",
        f"Failed to unsubscribe newsletter subscriber: {subscriber.id}. Record was not saved",
    )
    _sync_growth_subscriber_best_effort(subscriber)

    return jsonify(result="success", message="Unsubscribed successfully", subscriber=subscriber.to_dict), 200


@newsletter_blueprint.route("/update-language/<subscriber_id>", methods=["POST"])
def update_language_preferences(subscriber_id):
    data = request.get_json()
    new_language = data.get("language")

    if not new_language:
        raise InvalidRequest("New language is required", status_code=400)

    try:
        subscriber = NewsletterSubscriber.from_id(record_id=subscriber_id)
    except HTTPError as e:
        if e.response.status_code == 404:
            raise InvalidRequest("Subscriber not found", status_code=404)
        raise InvalidRequest(f"Failed to fetch subscriber: {e.response.text}", status_code=e.response.status_code)

    _save_newsletter_with_retry(
        lambda: subscriber.update_language(new_language),
        "Language update failed",
        f"Failed to update language preferences for newsletter subscriber: {subscriber.id}. Record was not saved",
    )
    _sync_growth_subscriber_best_effort(subscriber)

    return jsonify(result="success", message="Language updated successfully", subscriber=subscriber.to_dict), 200


@newsletter_blueprint.route("/send-latest/<subscriber_id>", methods=["GET"])
def send_latest_newsletter(subscriber_id):
    try:
        subscriber = NewsletterSubscriber.from_id(record_id=subscriber_id)
    except HTTPError as e:
        if e.response.status_code == 404:
            raise InvalidRequest("Subscriber not found", status_code=404)
        raise InvalidRequest(f"Failed to fetch subscriber: {e.response.text}", status_code=e.response.status_code)

    if subscriber.status != NewsletterSubscriber.Statuses.SUBSCRIBED.value:
        raise InvalidRequest(message=f"Cannot send to subscribers with status: {subscriber.status}", status_code=400)

    current_app.logger.info(f"Sending latest newsletter to new subscriber: {subscriber.id}")
    _send_latest_newsletter(subscriber.id, subscriber.email, subscriber.language)

    return jsonify(result="success", subscriber=subscriber.to_dict), 200


@newsletter_blueprint.route("/find-subscriber", methods=["GET"])
def get_subscriber():
    subscriber_id = request.args.get("subscriber_id")
    email = request.args.get("email")

    if not subscriber_id and not email:
        raise InvalidRequest("Subscriber ID or email is required", status_code=400)

    try:
        if subscriber_id:
            subscriber = NewsletterSubscriber.from_id(record_id=subscriber_id)
        elif email:
            subscriber = NewsletterSubscriber.from_email(email)
    except HTTPError as e:
        if e.response.status_code != 404:
            raise InvalidRequest(f"Failed to fetch subscriber: {e.response.text}", status_code=e.response.status_code)
        raise InvalidRequest("Subscriber not found", status_code=404)

    return jsonify(result="success", subscriber=subscriber.to_dict), 200


def _send_latest_newsletter(subscriber_id, recipient_email, language):
    # Get the current newsletter template IDs from Airtable
    try:
        latest_newsletter_templates = LatestNewsletterTemplate.get_latest_newsletter_templates()
    except HTTPError as e:
        if e.response.status_code == 404:
            raise InvalidRequest("No current newsletter templates found", status_code=404)
        raise InvalidRequest(
            f"Failed to fetch latest newsletter templates: {e.response.text}", status_code=e.response.status_code
        )

    # Fetch the template from the DB depending on the subscriber's language
    template = (
        dao_get_template_by_id(latest_newsletter_templates.template_id_en)
        if language == NewsletterSubscriber.Languages.EN.value
        else dao_get_template_by_id(latest_newsletter_templates.template_id_fr)
    )
    service = Service.query.get(current_app.config["NOTIFY_SERVICE_ID"])

    # Save and send the notification
    saved_notification = persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient=recipient_email,
        service=service,
        personalisation={"subscriber_id": subscriber_id},
        notification_type=EMAIL_TYPE,
        api_key_id=None,
        key_type=KEY_TYPE_NORMAL,
    )
    send_notification_to_queue(saved_notification, False, queue=QueueNames.NOTIFY)


def send_confirmation_email(subscriber_id, recipient_email, language):
    template_id = (
        current_app.config["NEWSLETTER_CONFIRMATION_EMAIL_TEMPLATE_ID_EN"]
        if language == "en"
        else current_app.config["NEWSLETTER_CONFIRMATION_EMAIL_TEMPLATE_ID_FR"]
    )
    template = dao_get_template_by_id(template_id)
    service = Service.query.get(current_app.config["NOTIFY_SERVICE_ID"])

    url = f"{current_app.config['ADMIN_BASE_URL']}/newsletter/confirm/{subscriber_id}"

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


def _save_newsletter_with_retry(save_operation, failure_message, error_log_message):
    last_error = None

    for attempt in range(1, NEWSLETTER_AIRTABLE_WRITE_MAX_ATTEMPTS + 1):
        try:
            result = save_operation()
            if getattr(result, "saved", True):
                return result
            last_error = RuntimeError("Record was not saved")
        except Exception as error:
            last_error = error

        if attempt < NEWSLETTER_AIRTABLE_WRITE_MAX_ATTEMPTS:
            current_app.logger.warning(
                "Retrying newsletter Airtable write (%s/%s)",
                attempt + 1,
                NEWSLETTER_AIRTABLE_WRITE_MAX_ATTEMPTS,
            )

    current_app.logger.error(error_log_message)
    if last_error:
        current_app.logger.warning("Last newsletter Airtable write error: %s", str(last_error))

    raise InvalidRequest(failure_message, status_code=500)


def _sync_growth_subscriber_best_effort(subscriber):
    if not _is_growth_table_configured():
        return

    last_error = None

    for attempt in range(1, NEWSLETTER_AIRTABLE_WRITE_MAX_ATTEMPTS + 1):
        try:
            result = _upsert_growth_subscriber(subscriber)
            if getattr(result, "saved", True):
                return
            last_error = RuntimeError("Record was not saved")
        except Exception as error:
            last_error = error

        if attempt < NEWSLETTER_AIRTABLE_WRITE_MAX_ATTEMPTS:
            current_app.logger.warning(
                "Retrying growth Airtable write for %s (%s/%s)",
                subscriber.email,
                attempt + 1,
                NEWSLETTER_AIRTABLE_WRITE_MAX_ATTEMPTS,
            )

    current_app.logger.warning(
        "Best-effort growth Airtable sync failed for %s: %s",
        subscriber.email,
        str(last_error) if last_error else "unknown error",
    )


def _upsert_growth_subscriber(subscriber):
    try:
        growth_subscriber = GrowthNewsletterSubscriber.from_email(subscriber.email)
        is_new_record = False
    except HTTPError as error:
        if error.response.status_code != 404:
            raise
        growth_subscriber = GrowthNewsletterSubscriber(email=subscriber.email)
        is_new_record = True

    growth_subscriber.language = subscriber.language
    growth_subscriber.status = subscriber.status
    growth_subscriber.created_at = subscriber.created_at
    growth_subscriber.confirmed_at = subscriber.confirmed_at
    growth_subscriber.unsubscribed_at = subscriber.unsubscribed_at
    growth_subscriber.has_resubscribed = subscriber.has_resubscribed

    if is_new_record and not getattr(growth_subscriber, "product", None):
        growth_subscriber.product = GrowthNewsletterSubscriber.DEFAULT_PRODUCT_NAME

    return growth_subscriber.save()


def _is_growth_table_configured():
    return bool(current_app.config.get("AIRTABLE_NEWSLETTER_GROWTH_TABLE_NAME")) and bool(
        current_app.config.get("AIRTABLE_API_KEY")
    )
