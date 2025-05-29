from typing import Any, List

from flask import current_app, json, jsonify
from jsonschema import ValidationError as JsonSchemaValidationError
from marshmallow import ValidationError
from notifications_utils.recipients import InvalidEmailError
from sqlalchemy.exc import DataError
from sqlalchemy.orm.exc import NoResultFound

from app.authentication.auth import AuthError
from app.exceptions import ArchiveValidationError


class VirusScanError(Exception):
    def __init__(self, message):
        super().__init__(message)


class InvalidRequest(Exception):
    code: Any = None
    fields: List[Any] = []

    def __init__(self, message, status_code):
        super().__init__()
        self.message = message
        self.status_code = status_code

    def to_dict(self):
        return {"result": "error", "message": self.message}

    def to_dict_v2(self):
        """
        Version 2 of the public api error response.
        """
        return {
            "status_code": self.status_code,
            "errors": [{"error": self.__class__.__name__, "message": self.message}],
        }

    def __str__(self):
        return str(self.to_dict())


class CannotRemoveUserError(InvalidRequest):
    message = "Cannot remove user from team"

    def __init__(self, fields=[], message=None, status_code=400):
        # Call parent class __init__ with message and status_code
        super().__init__(message=message if message else self.message, status_code=status_code)
        self.fields = fields


class UserAlreadyInServiceError(InvalidRequest):
    message = "This user is already in the service"

    def __init__(self, fields=[], message=None, status_code=409):
        # Call parent class __init__ with message and status_code
        super().__init__(message=message if message else self.message, status_code=status_code)
        self.fields = fields


class DuplicateEntityError(InvalidRequest):
    """Generic error for handling unique constraint errors. This error should be subclassed to provide more specific error messages depending on the entity
       and their unique fields.

    Args:
        entity (str): The name of the entity that was saved/updated and triggered an IntegrityError. E.g. Template Category, Email Branding, Service, etc.
        fields (list): List of fields associated with the DB entity that must be unique.
    """

    entity: str = "Entity"

    def __init__(self, fields=[], entity=None, status_code=400):
        self.entity = entity if entity else self.entity
        self.fields = fields
        message = "{} already exists, {}"

        num_fields = len(fields)
        if num_fields > 0:
            formatted_fields = ""
            if num_fields == 1:
                # e.g. "name must be unique"
                formatted_fields = f"{fields[0]} must be unique."
            elif num_fields >= 2:
                # e.g. "name_en and name_fr must be unique" or "name_en, name_fr, and phone_number must be unique"
                formatted_fields = f"{', '.join(fields[:-1])} and {fields[-1]} must be unique."
            message = message.format(self.entity, formatted_fields)
        else:
            # Default fallback when no specific entity or required unique fields are present "Entity already exists."
            message = message.format(self.entity, "").replace(",", ".").strip()

        super().__init__(message=message, status_code=status_code)


class CannotSaveDuplicateEmailBrandingError(DuplicateEntityError):
    entity = "Email branding"
    fields = ["name"]

    def __init__(self, status_code=400):
        super().__init__(fields=self.fields, entity=self.entity, status_code=status_code)


class CannotSaveDuplicateTemplateCategoryError(DuplicateEntityError):
    entity = "Template category"
    fields = ["name_en", "name_fr"]

    def __init__(self, status_code=400):
        super().__init__(fields=self.fields, entity=self.entity, status_code=status_code)


def register_errors(blueprint):  # noqa: C901
    @blueprint.errorhandler(CannotSaveDuplicateEmailBrandingError)
    def cannot_save_duplicate_email_branding_error(error):
        response = jsonify(error.to_dict())
        response.status_code = error.status_code
        current_app.logger.info(error.message)
        return response

    @blueprint.errorhandler(CannotSaveDuplicateTemplateCategoryError)
    def cannot_save_duplicate_template_category_error(error):
        response = jsonify(error.to_dict())
        response.status_code = error.status_code
        current_app.logger.info(error.message)
        return response

    @blueprint.errorhandler(CannotRemoveUserError)
    def cannot_remove_user_error(error):
        response = jsonify(error.to_dict())
        response.status_code = error.status_code
        current_app.logger.info(error.message)
        return response

    @blueprint.errorhandler(InvalidEmailError)
    def invalid_format(error):
        # Please not that InvalidEmailError is re-raised for InvalidEmail or InvalidPhone,
        # work should be done in the utils app to tidy up these errors.
        return jsonify(result="error", message=str(error)), 400

    @blueprint.errorhandler(AuthError)
    def authentication_error(error):
        return jsonify(result="error", message=error.message), error.code

    @blueprint.errorhandler(ValidationError)
    def marshmallow_validation_error(error):
        current_app.logger.info(error)
        return jsonify(result="error", message=error.messages), 400

    @blueprint.errorhandler(JsonSchemaValidationError)
    def jsonschema_validation_error(error):
        current_app.logger.info(error)
        return jsonify(json.loads(error.message)), 400

    @blueprint.errorhandler(ArchiveValidationError)
    def archive_validation_error(error):
        current_app.logger.info(error)
        return jsonify(result="error", message=str(error)), 400

    @blueprint.errorhandler(InvalidRequest)
    def invalid_data(error):
        response = jsonify(error.to_dict())
        response.status_code = error.status_code
        current_app.logger.info(error)
        return response

    @blueprint.errorhandler(400)
    def bad_request(e):
        msg = e.description or "Invalid request parameters"
        current_app.logger.exception(msg)
        return jsonify(result="error", message=str(msg)), 400

    @blueprint.errorhandler(401)
    def unauthorized(e):
        error_message = "Unauthorized, authentication token must be provided"
        return (
            jsonify(result="error", message=error_message),
            401,
            [("WWW-Authenticate", "Bearer")],
        )

    @blueprint.errorhandler(403)
    def forbidden(e):
        error_message = "Forbidden, invalid authentication token provided"
        return jsonify(result="error", message=error_message), 403

    @blueprint.errorhandler(429)
    def limit_exceeded(e):
        current_app.logger.exception(e)
        return jsonify(result="error", message=str(e.description)), 429

    @blueprint.errorhandler(NoResultFound)
    @blueprint.errorhandler(DataError)
    def no_result_found(e):
        current_app.logger.info(e)
        return jsonify(result="error", message="No result found"), 404

    # this must be defined after all other error handlers since it catches the generic Exception object
    @blueprint.app_errorhandler(500)
    @blueprint.errorhandler(Exception)
    def internal_server_error(e):
        # if e is a werkzeug InternalServerError then it may wrap the original exception. For more details see:
        # https://flask.palletsprojects.com/en/1.1.x/errorhandling/?highlight=internalservererror#unhandled-exceptions
        e = getattr(e, "original_exception", e)
        current_app.logger.exception(e)
        return jsonify(result="error", message="Internal server error"), 500
