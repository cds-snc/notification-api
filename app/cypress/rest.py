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

"""
This module will be used by the cypress tests to create users on the fly whenever a test suite is run.

Additionally, this module will also be used to clean up test users periodically to keep the data footprint small.
"""

cypress_blueprint = Blueprint("cypress", __name__)
register_errors(cypress_blueprint)


@cypress_blueprint.route("/create_user/<email_name>", methods=["POST"])
def create_test_user(email_name):
    data = request.get_json()
    password = data.get("password")

    if current_app.config["NOTIFY_ENVIRONMENT"] == "production":
        return jsonify(message="Forbidden"), 403

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

        print("removal success: " + email_name)
    except Exception as e:
        print(f"Error cleaning up test user: {e}")
        db.session.rollback()


"""
Endpoint for cleaning up stale users.  This endpoint will only be used internally by the Cypress tests.

This endpoint is responsible for removing stale testing users from the database.
Stale users are identified as users whose email addresses match the pattern "%notify-ui-tests+%@cds-snc.ca%" and whose creation time is older than three hours ago.

Returns:
    A JSON response with a success message if the cleanup is successful, or an error message if an exception occurs during the cleanup process.
"""


@cypress_blueprint.route("/cleanup", methods=["GET"])
def cleanup_stale_users():
    if current_app.config["NOTIFY_ENVIRONMENT"] == "production":
        return jsonify(message="Forbidden"), 403

    three_hours_ago = datetime.utcnow() - timedelta(hours=3)
    users = User.query.filter(User.email_address.like("%notify-ui-tests+%@cds-snc.ca%"), User.created_at < three_hours_ago).all()

    # get the list of email_address property from users
    users_emails = [user for user in users]

    print("users to clean: " + str(users_emails))

    # loop through users and call destroy_user on each one
    for user in users:
        user_email = user.email_address.split("+")[1].split("@")[0]
        print("Trying to remove:" + user_email)

        try:
            _destroy_test_user(user_email)
        except Exception:
            return jsonify(message="Error cleaning up"), 500

    db.session.commit()
    return jsonify(message="Zeds dead, baby"), 201
