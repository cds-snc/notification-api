import json

from flask import jsonify, current_app, request
from jsonschema import ValidationError
from notifications_utils.recipients import InvalidEmailError
from sqlalchemy.exc import DataError
from sqlalchemy.orm.exc import NoResultFound

from app.authentication.auth import AuthError
from app.errors import InvalidRequest


class JobIncompleteError(Exception):
    def __init__(self, message):
        self.message = message
        self.status_code = 500

    def to_dict_v2(self):
        return {
            'status_code': self.status_code,
            "errors": [
                {
                    "error": 'JobIncompleteError',
                    "message": self.message
                }
            ]
        }


class TooManyRequestsError(InvalidRequest):
    status_code = 429
    message_template = 'Exceeded send limits ({}) for today'

    def __init__(self, sending_limit):
        self.message = self.message_template.format(sending_limit)


class LiveServiceTooManyRequestsError(TooManyRequestsError):
    pass


class TrialServiceTooManyRequestsError(TooManyRequestsError):
    pass


class RateLimitError(InvalidRequest):
    status_code = 429
    message_template = 'Exceeded rate limit for key type {} of {} requests per {} seconds'

    def __init__(self, sending_limit, interval, key_type):
        # normal keys are spoken of as "live" in the documentation
        # so using this in the error messaging
        if key_type == 'normal':
            key_type = 'live'

        self.message = self.message_template.format(key_type.upper(), sending_limit, interval)


class BadRequestError(InvalidRequest):
    message = "An error occurred"

    def __init__(self, fields=[], message=None, status_code=400):
        self.status_code = status_code
        self.fields = fields
        self.message = message if message else self.message


class PDFNotReadyError(BadRequestError):
    def __init__(self):
        super().__init__(message='PDF not available yet, try again later', status_code=400)


def register_errors(blueprint):
    @blueprint.errorhandler(InvalidEmailError)
    def invalid_format(error):
        # Please not that InvalidEmailError is re-raised for InvalidEmail or InvalidPhone,
        # work should be done in the utils app to tidy up these errors.
        current_app.logger.info(error)
        return jsonify(status_code=400,
                       errors=[{"error": error.__class__.__name__, "message": str(error)}]), 400

    @blueprint.errorhandler(InvalidRequest)
    def invalid_data(error):
        current_app.logger.info(error)
        response = jsonify(error.to_dict_v2()), error.status_code
        return response

    @blueprint.errorhandler(ValidationError)
    def validation_error(error):
        current_app.logger.info(error)
        return jsonify(json.loads(error.message)), 400

    @blueprint.errorhandler(JobIncompleteError)
    def job_incomplete_error(error):
        return jsonify(error.to_dict_v2()), 500

    @blueprint.errorhandler(NoResultFound)
    @blueprint.errorhandler(DataError)
    def no_result_found(e):
        current_app.logger.info(e)
        return jsonify(status_code=404,
                       errors=[{"error": e.__class__.__name__, "message": "No result found"}]), 404

    @blueprint.errorhandler(AuthError)
    def auth_error(error):
        current_app.logger.info('API AuthError, client: {} error: {}'.format(request.headers.get('User-Agent'), error))
        return jsonify(error.to_dict_v2()), error.code

    @blueprint.errorhandler(Exception)
    def internal_server_error(error):
        current_app.logger.exception(error)
        return jsonify(status_code=500,
                       errors=[{"error": error.__class__.__name__, "message": 'Internal server error'}]), 500
