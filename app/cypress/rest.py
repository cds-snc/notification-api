import uuid
from flask import Blueprint, jsonify, request

from app import db
from app.dao.services_dao import dao_add_user_to_service
from app.dao.templates_dao import dao_update_template
from app.dao.users_dao import save_model_user
from app.errors import register_errors
from app.models import LoginEvent, Permission, Service, ServiceUser, Template, TemplateHistory, User, VerifyCode

cypress_blueprint = Blueprint("cypress", __name__)
register_errors(cypress_blueprint)

@cypress_blueprint.route("/create_user/<email_name>", methods=["POST"])
def create_test_user(email_name):
    data = request.get_json()
    password = data.get('password')

    if current_app.config["NOTIFY_ENVIRONMENT"] == "production":
        return jsonify(message="Forbidden"), 403

    # Create the user
    data = {
        "id": uuid.uuid4(),
        "name": "Notify UI testing account",
        "email_address": f"notify-ui-tests+{email_name}@cds-snc.ca",
        "password": hashlib.sha256((password + current_app.config["DANGEROUS_SALT"]).encode("utf-8")).hexdigest(), #"e01221bcb56f1fb931c0ca310e2a13e23390b267b4cd80dc36366b6c9ef8eb5d", # TODO: move this to a secret!
        "mobile_number": "9025555555",
        "state": "active",
        "blocked": False,
    }
    
    user = User(**data)
    save_model_user(user)

    # add user to cypress service w/ full permissions
    service = Service.query.filter_by(id="5c8a0501-2aa8-433a-ba51-cefb8063ab93").first()
    permissions = []
    for p in ["manage_users", "manage_templates", "manage_settings", "send_texts", "send_emails", "send_letters", "manage_api_keys", "view_activity"]:
        permissions.append(Permission(permission=p))
    
    dao_add_user_to_service(service, user, permissions=permissions)

    # things to delete
    # login_events
    # verify_codes

    return jsonify(user.serialize()), 201


@cypress_blueprint.route("/destroy_user/<email_name>", methods=["GET"])
def destroy_user(email_name):
    user = User.query.filter_by(email_address=f"notify-ui-tests+{email_name}@cds-snc.ca").first()
    
    if not user:
        return
    
    # update the created_by field for each template to use id NOTIFY_TEST_USER_ID
    templates = Template.query.filter_by(created_by=user).all()
    for template in templates:
        template.created_by_id = NOTIFY_TEST_USER_ID
        dao_update_template(template)

    # update the created_by field for each template to use id NOTIFY_TEST_USER_ID
    history_templates = TemplateHistory.query.filter_by(created_by=user).all()
    for templateh in history_templates:
        templateh.created_by_id = NOTIFY_TEST_USER_ID
        db.session.add(templateh)

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

    db.session.commit()

    return jsonify(message="Zeds dead, baby"), 201

@cypress_blueprint.route("/cleanup", methods=["GET"])
def cleanup_users():
    users = User.query.filter(User.email_address.like(f"%notify-ui-tests+%@cds-snc.ca%"))

    # loop through users and call destroy_user on each one
    for user in users:
        user_email = user.email_address.split("+")[1].split("@")[0]
        print(user_email)
        destroy_user(user_email)