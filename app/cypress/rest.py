"""
This module will be used by the cypress tests to create users on the fly whenever a test suite is run, and clean
them up periodically to keep the data footprint small.
"""

import hashlib
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request

from app import db
from app.dao.services_dao import dao_add_user_to_service
from app.dao.templates_dao import dao_update_template
from app.dao.users_dao import save_model_user
from app.errors import register_errors
from app.models import LoginEvent, Permission, Service, ServiceUser, Template, TemplateHistory, TemplateRedacted, User, VerifyCode

cypress_blueprint = Blueprint("cypress", __name__)
register_errors(cypress_blueprint)


@cypress_blueprint.route("/create_user/<email_name>", methods=["POST"])
def create_test_user(email_name):
    """
    Create a test user for Notify UI testing.

    Args:
        email_name (str): The name to be used in the email address of the test user.

    Returns:
        dict: A dictionary containing the serialized user information.
    """
    if current_app.config["NOTIFY_ENVIRONMENT"] == "production":
        return jsonify(message="Forbidden"), 403

    try:
        data = request.get_json()
        password = data.get("password")
    except Exception:
        return jsonify(message="Invalid JSON"), 400

    try:
        # Create the user
        data = {
            "id": uuid.uuid4(),
            "name": "Notify UI testing account",
            "email_address": f"notify-ui-tests+{email_name}@cds-snc.ca",
            "password": hashlib.sha256((password + current_app.config["DANGEROUS_SALT"]).encode("utf-8")).hexdigest(),
            "mobile_number": "9025555555",
            "state": "active",
            "blocked": False,
        }

        user = User(**data)
        save_model_user(user)

        # add user to cypress service w/ full permissions
        service = Service.query.filter_by(id="5c8a0501-2aa8-433a-ba51-cefb8063ab93").first()
        permissions = []
        for p in [
            "manage_users",
            "manage_templates",
            "manage_settings",
            "send_texts",
            "send_emails",
            "send_letters",
            "manage_api_keys",
            "view_activity",
        ]:
            permissions.append(Permission(permission=p))

        dao_add_user_to_service(service, user, permissions=permissions)

    except Exception:
        return jsonify(message="Error creating user"), 400

    return jsonify(user.serialize()), 201


def _destroy_test_user(email_name):
    CYPRESS_TEST_USER_ID = current_app.config["CYPRESS_TEST_USER_ID"]

    user = User.query.filter_by(email_address=f"notify-ui-tests+{email_name}@cds-snc.ca").first()

    if not user:
        return

    try:
        # update the created_by field for each template to use id CYPRESS_TEST_USER_ID
        templates = Template.query.filter_by(created_by=user).all()
        for template in templates:
            template.created_by_id = CYPRESS_TEST_USER_ID
            dao_update_template(template)

        # update the created_by field for each template to use id CYPRESS_TEST_USER_ID
        history_templates = TemplateHistory.query.filter_by(created_by=user).all()
        for templateh in history_templates:
            templateh.created_by_id = CYPRESS_TEST_USER_ID
            db.session.add(templateh)

        # update the created_by field for each template_redacted to use id CYPRESS_TEST_USER_ID
        redacted_templates = TemplateRedacted.query.filter_by(updated_by=user).all()
        for templater in redacted_templates:
            templater.updated_by_id = CYPRESS_TEST_USER_ID
            db.session.add(templater)

        # Update services create by this user to use CYPRESS_TEST_USER_ID
        services = Service.query.filter_by(created_by=user).all()
        for service in services:
            service.created_by_id = CYPRESS_TEST_USER_ID
            db.session.add(service)

        # remove all the login events for this user
        LoginEvent.query.filter_by(user=user).delete()

        # remove all permissions for this user
        Permission.query.filter_by(user=user).delete()

        # remove user_to_service entries
        ServiceUser.query.filter_by(user_id=user.id).delete()

        # remove verify codes
        VerifyCode.query.filter_by(user=user).delete()

        # remove the user
        User.query.filter_by(email_address=f"notify-ui-tests+{email_name}@cds-snc.ca").delete()

    except Exception:
        db.session.rollback()


@cypress_blueprint.route("/cleanup", methods=["GET"])
def cleanup_stale_users():
    """
    Endpoint for cleaning up stale users.  This endpoint will only be used internally by the Cypress tests.

    This endpoint is responsible for removing stale testing users from the database.
    Stale users are identified as users whose email addresses match the pattern "%notify-ui-tests+%@cds-snc.ca%" and whose creation time is older than three hours ago.

    If this is accessed from production, it will return a 403 Forbidden response.

    Returns:
        A JSON response with a success message if the cleanup is successful, or an error message if an exception occurs during the cleanup process.
    """
    if current_app.config["NOTIFY_ENVIRONMENT"] == "production":
        return jsonify(message="Forbidden"), 403

    try:
        three_hours_ago = datetime.utcnow() - timedelta(hours=3)
        users = User.query.filter(
            User.email_address.like("%notify-ui-tests+%@cds-snc.ca%"), User.created_at < three_hours_ago
        ).all()

        # loop through users and call destroy_user on each one
        for user in users:
            user_email = user.email_address.split("+")[1].split("@")[0]
            _destroy_test_user(user_email)

        db.session.commit()
    except Exception:
        return jsonify(message="Error cleaning up"), 500

    return jsonify(message="Zeds dead, baby"), 201
