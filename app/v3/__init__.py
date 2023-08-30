from app.authentication.auth import AuthError
from flask import Blueprint
from jsonschema import ValidationError

v3_blueprint = Blueprint("v3", __name__, url_prefix='/v3')


########################################
# Error handlers common to all v3 routes
########################################

@v3_blueprint.errorhandler(AuthError)
def auth_error(error):
    return error.to_dict_v3(), error.code


@v3_blueprint.errorhandler(ValidationError)
def validation_error(error):
    return {
        "errors": [
            {
                "error": "ValidationError",
                "message": error.message,
            }
        ]
    }, 400
