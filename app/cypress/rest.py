"""
This module will be used by the cypress tests to create users on the fly whenever a test suite is run, and clean
them up periodically to keep the data footprint small.
"""

import hashlib
import re
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify

from app import db
from app.dao.services_dao import dao_add_user_to_service
from app.dao.users_dao import save_model_user
from app.errors import register_errors
from app.models import (
    AnnualBilling,
    LoginEvent,
    Permission,
    Service,
    ServicePermission,
    ServiceUser,
    Template,
    TemplateHistory,
    TemplateRedacted,
    User,
    VerifyCode,
)

cypress_blueprint = Blueprint("cypress", __name__)
register_errors(cypress_blueprint)

EMAIL_PREFIX = "notify-ui-tests+ag_"


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

    # Sanitize email_name to allow only alphanumeric characters
    if not re.match(r"^[a-z0-9]+$", email_name):
        return jsonify(message="Invalid email name"), 400

    try:
        # Create the users
        user_regular = {
            "id": uuid.uuid4(),
            "name": "Notify UI testing account",
            "email_address": f"{EMAIL_PREFIX}{email_name}@cds-snc.ca",
            "password": hashlib.sha256(
                (current_app.config["CYPRESS_USER_PW_SECRET"] + current_app.config["DANGEROUS_SALT"]).encode("utf-8")
            ).hexdigest(),
            "mobile_number": "9025555555",
            "state": "active",
            "blocked": False,
        }

        user = User(**user_regular)
        save_model_user(user)

        # Create the users
        user_admin = {
            "id": uuid.uuid4(),
            "name": "Notify UI testing account",
            "email_address": f"{EMAIL_PREFIX}{email_name}_admin@cds-snc.ca",
            "password": hashlib.sha256(
                (current_app.config["CYPRESS_USER_PW_SECRET"] + current_app.config["DANGEROUS_SALT"]).encode("utf-8")
            ).hexdigest(),
            "mobile_number": "9025555555",
            "state": "active",
            "blocked": False,
            "platform_admin": True,
        }

        user2 = User(**user_admin)
        save_model_user(user2)

        # add user to cypress service w/ full permissions
        service = Service.query.filter_by(id=current_app.config["CYPRESS_SERVICE_ID"]).first()
        permissions_reg = []
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
            permissions_reg.append(Permission(permission=p))

        dao_add_user_to_service(service, user, permissions=permissions_reg)

        permissions_admin = []
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
            permissions_admin.append(Permission(permission=p))
        dao_add_user_to_service(service, user2, permissions=permissions_admin)

        current_app.logger.info(f"Created test user {user.email_address} and {user2.email_address}")
    except Exception:
        return jsonify(message="Error creating user"), 400

    users = {"regular": user.serialize(), "admin": user2.serialize()}

    return jsonify(users), 201


def _destroy_test_user(email_name):
    user = User.query.filter_by(email_address=f"{EMAIL_PREFIX}{email_name}@cds-snc.ca").first()

    if not user:
        current_app.logger.error(f"Error destroying test user {user.email_address}: no user found")
        return

    try:
        # update the cypress service's created_by to be the main cypress user
        # this value gets changed when updating branding (and possibly other updates to service)
        # and is a bug
        cypress_service = Service.query.filter_by(id=current_app.config["CYPRESS_SERVICE_ID"]).first()
        cypress_service.created_by_id = current_app.config["CYPRESS_TEST_USER_ID"]

        # cycle through all the services created by this user, remove associated entities
        services = Service.query.filter_by(created_by=user).filter(Service.id != current_app.config["CYPRESS_SERVICE_ID"])
        for service in services.all():
            # Delete template history except for smoke test templates
            TemplateHistory.query.filter(
                TemplateHistory.service_id == service.id,
                ~TemplateHistory.id.in_(
                    [
                        current_app.config["CYPRESS_SMOKE_TEST_EMAIL_TEMPLATE_ID"],
                        current_app.config["CYPRESS_SMOKE_TEST_SMS_TEMPLATE_ID"],
                    ]
                ),
            ).delete()

            # Delete templates except for smoke test templates
            Template.query.filter(
                Template.service_id == service.id,
                ~Template.id.in_(
                    [
                        current_app.config["CYPRESS_SMOKE_TEST_EMAIL_TEMPLATE_ID"],
                        current_app.config["CYPRESS_SMOKE_TEST_SMS_TEMPLATE_ID"],
                    ]
                ),
            ).delete()
            AnnualBilling.query.filter_by(service_id=service.id).delete()
            ServicePermission.query.filter_by(service_id=service.id).delete()
            Permission.query.filter_by(service_id=service.id).delete()

        services.delete()

        # remove all entities related to the user itself
        TemplateRedacted.query.filter_by(updated_by=user).delete()
        # Delete template history except for smoke test templates
        TemplateHistory.query.filter(
            TemplateHistory.created_by == user,
            ~TemplateHistory.id.in_(
                [
                    current_app.config["CYPRESS_SMOKE_TEST_EMAIL_TEMPLATE_ID"],
                    current_app.config["CYPRESS_SMOKE_TEST_SMS_TEMPLATE_ID"],
                ]
            ),
        ).delete()
        # Delete templates except for smoke test templates
        Template.query.filter(
            Template.created_by == user,
            ~Template.id.in_(
                [
                    current_app.config["CYPRESS_SMOKE_TEST_EMAIL_TEMPLATE_ID"],
                    current_app.config["CYPRESS_SMOKE_TEST_SMS_TEMPLATE_ID"],
                ]
            ),
        ).delete()
        Permission.query.filter_by(user=user).delete()
        LoginEvent.query.filter_by(user=user).delete()
        ServiceUser.query.filter_by(user_id=user.id).delete()
        VerifyCode.query.filter_by(user=user).delete()
        User.query.filter_by(email_address=f"{EMAIL_PREFIX}{email_name}@cds-snc.ca").delete()

        db.session.commit()

    except Exception as e:
        current_app.logger.error(f"Error destroying test user {user.email_address}: {str(e)}")
        db.session.rollback()


@cypress_blueprint.route("/cleanup", methods=["GET"])
def cleanup_stale_users():
    """
    Method for cleaning up stale users.  This method will only be used internally by the Cypress tests.

    This method is responsible for removing stale testing users from the database.
    Stale users are identified as users whose email addresses match the pattern "%notify-ui-tests+ag_%@cds-snc.ca%" and whose creation time is older than three hours ago.

    If this is accessed from production, it will return a 403 Forbidden response.

    Returns:
        A JSON response with a success message if the cleanup is successful, or an error message if an exception occurs during the cleanup process.
    """
    if current_app.config["NOTIFY_ENVIRONMENT"] == "production":
        return jsonify(message="Forbidden"), 403

    try:
        three_hours_ago = datetime.utcnow() - timedelta(hours=3)
        users = User.query.filter(
            User.email_address.like(f"%{EMAIL_PREFIX}%@cds-snc.ca%"), User.created_at < three_hours_ago
        ).all()

        # loop through users and call destroy_user on each one
        for user in users:
            user_email = user.email_address.split("+ag_")[1].split("@")[0]
            _destroy_test_user(user_email)

        db.session.commit()
    except Exception:
        current_app.logger.error("[cleanup_stale_users]: error cleaning up test users")
        return jsonify(message="Error cleaning up"), 500

    current_app.logger.info("[cleanup_stale_users]: Cleaned up stale test users")
    return jsonify(message="Clean up complete"), 201
