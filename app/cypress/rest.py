import uuid
from flask import Blueprint, jsonify, request

from app.dao.users_dao import save_model_user
from app.errors import register_errors
from app.models import User

cypress_blueprint = Blueprint("cypress", __name__)
register_errors(cypress_blueprint)


@cypress_blueprint.route("/start_test_suite/<email_name>", methods=["GET"])
def create_test_user(email_name):
    # Create the user
    data = {
        "id": uuid.uuid4(),
        "name": "Notify UI testing account",
        "email_address": f"notify-ui-tests+{email_name}@cds-snc.ca",
        "password": "", # TODO: move this to a secret!
        "mobile_number": "9025555555",
        "state": "active",
        "blocked": False,
    }
    
    user = User(**data)
    save_model_user(user)

    # add user to cypress service w/ full permissions
    # things to delete
    # login_events
    # verify_codes

    return jsonify(user.serialize()), 201

@cypress_blueprint.route("/end_test_suite/<email_name>", methods=["GET"])
def create_test_user(email_name):
    # Delete the user
    # Things to remove:
    # login_events
    # verify_codes
    # user
    

    return jsonify(message="yo"), 201
