from app.authentication.auth import AuthError
from flask import Blueprint
from jsonschema import ValidationError
from werkzeug.exceptions import BadRequest

v3_blueprint = Blueprint("v3", __name__, url_prefix='/v3')


########################################
# Error handlers common to all v3 routes
########################################

@v3_blueprint.errorhandler(AuthError)
def auth_error(error):
    """
    Generally 401 and 403 errors.
    """

    return error.to_dict_v3(), error.code


@v3_blueprint.errorhandler(BadRequest)
def bad_request(error):
    """
    This is for 400 responses not caused by schema validation failure.  If error.__cause__
    is not None, the syntax "raise BadRequest from <exception>" raised the exception.
    """

    return {
        "errors": [
            {
                "error": "BadRequest",
                "message": str(error.__cause__) if (error.__cause__ is not None) else str(error),
            }
        ]
    }, 400


@v3_blueprint.errorhandler(ValidationError)
def schema_validation_error(error):
    """
    This is for schema validation errors, which should result in a 400 response.
    """

    if "is not valid under any of the given schemas" in error.message and "anyOfValidationMessage" in error.schema:
        # This is probably a failure of an "anyOf" clause, and the default error message is not helpful.
        error_message = error.schema["anyOfValidationMessage"]
    else:
        error_message = error.message

    return {
        "errors": [
            {
                "error": "ValidationError",
                "message": error_message,
            }
        ]
    }, 400


@v3_blueprint.errorhandler(NotImplementedError)
def not_implemented_error(error):
    return {
        "errors": [
            {
                "error": "NotImplementedError",
                "message": str(error),
            }
        ]
    }, 501
