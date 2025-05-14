"""
Example implementation of how to add OpenAPI documentation to existing routes.

This file demonstrates two approaches:
1. Using Flask-RESTx Resource classes (recommended)
2. Using custom decorators (legacy)

This is a demonstration file and should not be imported directly.
"""

from flask_restx import Resource

from app.v2.notifications import models, notifications_namespace, v2_notification_blueprint
from app.v2.openapi.decorators import api_route, document_response


# Example 1: Using Flask-RESTx Resource classes (RECOMMENDED APPROACH)
@notifications_namespace.route("/example/sms")
class SMSNotificationResource(Resource):
    @notifications_namespace.doc("send_sms_notification")
    @notifications_namespace.expect(models["sms_request"])
    @notifications_namespace.response(201, "SMS notification created successfully", models["sms_response"])
    @notifications_namespace.response(400, "Bad request")
    @notifications_namespace.response(401, "Authentication error")
    def post(self):
        """
        Send an SMS notification.
        """
        # This would call your existing code
        # return post_notification(SMS_TYPE)
        pass


@notifications_namespace.route("/example/bulk")
class BulkNotificationResource(Resource):
    @notifications_namespace.doc("send_bulk_notifications")
    @notifications_namespace.expect(models["bulk_request"])
    @notifications_namespace.response(201, "Bulk notifications created successfully", models["bulk_response"])
    @notifications_namespace.response(400, "Bad request")
    @notifications_namespace.response(401, "Authentication error")
    @notifications_namespace.response(403, "Forbidden")
    def post(self):
        """
        Send bulk notifications.
        """
        # Implementation would go here
        return {"job_id": "example-job-id"}, 201


# Example 2: Legacy approach using custom decorators
# NOTE: This approach is shown for comparison only and should not be used for new endpoints
@v2_notification_blueprint.route("/example/email", methods=["POST"])
@document_response
@api_route(
    namespace=notifications_namespace,
    name="send_email_notification",
    description="Send an email notification",
    model=models["email_request"],
    responses={
        201: f"Email notification created successfully (model: {models['email_response']})",
        400: "Bad request",
        401: "Authentication error",
    },
)
def post_email_notification():
    """
    Send an email notification.
    """
    # This would call your existing code
    # return post_notification(EMAIL_TYPE)
    pass
