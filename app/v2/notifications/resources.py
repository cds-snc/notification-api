"""
Implementation of Flask-RESTx Resource classes for the Notifications API.

This module provides RESTful endpoints for sending notifications using
Flask-RESTx Resource classes instead of function-based views with custom decorators.
"""

import werkzeug
from flask import abort, current_app, request
from flask_restx import Resource

from app import (
    authenticated_service,
)
from app.models import (
    EMAIL_TYPE,
    SMS_TYPE,
)
from app.v2.errors import BadRequestError
from app.v2.notifications import models, notifications_namespace

# Import the functions from post_notifications.py that are used by these resources
# These functions should be kept as they are for compatibility
from app.v2.notifications.post_notifications import (
    _seed_bounce_data,
)


@notifications_namespace.route("/bulk")
class BulkNotificationsResource(Resource):
    @notifications_namespace.doc("send_bulk_notifications")
    @notifications_namespace.expect(models["bulk_request"])
    @notifications_namespace.response(201, "Bulk notifications created successfully", models["bulk_response"])
    @notifications_namespace.response(400, "Bad request")
    @notifications_namespace.response(401, "Authentication error")
    @notifications_namespace.response(403, "Forbidden")
    @notifications_namespace.response(429, "Rate limit exceeded")
    def post(self):
        """
        Send bulk notifications.
        """
        try:
            request.get_json()
        except werkzeug.exceptions.BadRequest as e:
            raise BadRequestError(message=f"Error decoding arguments: {e.description}", status_code=400)
        except werkzeug.exceptions.UnsupportedMediaType as e:
            raise BadRequestError(
                message="UnsupportedMediaType error: {}".format(e.description),
                status_code=415,
            )

        epoch_seeding_bounce = current_app.config["FF_BOUNCE_RATE_SEED_EPOCH_MS"]
        if epoch_seeding_bounce:
            _seed_bounce_data(epoch_seeding_bounce, str(authenticated_service.id))

        # Call the existing implementation function with the received parameters
        # This implementation needs to be migrated from post_notifications.py
        # but maintaining it here for compatibility
        from app.v2.notifications.post_notifications import post_bulk as post_bulk_impl

        return post_bulk_impl()


@notifications_namespace.route("/<notification_type>")
class GenericNotificationResource(Resource):
    @notifications_namespace.doc("send_notification")
    @notifications_namespace.response(201, "Notification created successfully")
    @notifications_namespace.response(400, "Bad request")
    @notifications_namespace.response(401, "Authentication error")
    @notifications_namespace.response(403, "Forbidden")
    @notifications_namespace.response(429, "Rate limit exceeded")
    def post(self, notification_type):
        """
        Send a notification.
        This is a generic endpoint that handles SMS and email notifications.
        """
        if notification_type == SMS_TYPE:
            return SMSNotificationResource().post()
        elif notification_type == EMAIL_TYPE:
            return EmailNotificationResource().post()
        else:
            abort(404)


@notifications_namespace.route("/{}".format(SMS_TYPE))
class SMSNotificationResource(Resource):
    @notifications_namespace.doc("send_sms_notification")
    @notifications_namespace.expect(models["sms_request"])
    @notifications_namespace.response(201, "SMS notification created successfully", models["sms_response"])
    @notifications_namespace.response(400, "Bad request")
    @notifications_namespace.response(401, "Authentication error")
    @notifications_namespace.response(403, "Forbidden")
    def post(self):
        """
        Send an SMS notification.
        """
        # Call the existing implementation function with the received parameters
        # This implementation needs to be migrated from post_notifications.py
        from app.v2.notifications.post_notifications import post_notification

        return post_notification(SMS_TYPE)


@notifications_namespace.route("/{}".format(EMAIL_TYPE))
class EmailNotificationResource(Resource):
    @notifications_namespace.doc("send_email_notification")
    @notifications_namespace.expect(models["email_request"])
    @notifications_namespace.response(201, "Email notification created successfully", models["email_response"])
    @notifications_namespace.response(400, "Bad request")
    @notifications_namespace.response(401, "Authentication error")
    @notifications_namespace.response(403, "Forbidden")
    def post(self):
        """
        Send an email notification.
        """
        # Call the existing implementation function with the received parameters
        # This implementation needs to be migrated from post_notifications.py
        from app.v2.notifications.post_notifications import post_notification

        return post_notification(EMAIL_TYPE)
