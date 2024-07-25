import json
from datetime import datetime, timedelta
from uuid import UUID

from flask import current_app
from iso8601 import ParseError, iso8601
from jsonschema import Draft7Validator, FormatChecker, ValidationError
from notifications_utils.recipients import (
    InvalidEmailError,
    InvalidPhoneError,
    validate_email_address,
    validate_phone_number,
)

from app.notifications.validators import validate_personalisation_and_decode_files

format_checker = FormatChecker()


@format_checker.checks("validate_uuid", raises=Exception)
def validate_uuid(instance):
    if isinstance(instance, str):
        UUID(instance)
    return True


@format_checker.checks("phone_number", raises=InvalidPhoneError)
def validate_schema_phone_number(instance):
    if isinstance(instance, str):
        validate_phone_number(instance, international=True)
    return True


@format_checker.checks("email_address", raises=InvalidEmailError)
def validate_schema_email_address(instance):
    if isinstance(instance, str):
        validate_email_address(instance)
    return True


@format_checker.checks("postage", raises=ValidationError)
def validate_schema_postage(instance):
    if isinstance(instance, str):
        if instance not in ["first", "second"]:
            raise ValidationError("invalid. It must be either first or second.")
    return True


@format_checker.checks("datetime_within_next_day", raises=ValidationError)
def validate_schema_date_with_hour(instance):
    if isinstance(instance, str):
        try:
            dt = iso8601.parse_date(instance).replace(tzinfo=None)
            if dt < datetime.utcnow():
                raise ValidationError("datetime cannot be in the past")
            if dt > datetime.utcnow() + timedelta(hours=24):
                raise ValidationError("datetime can only be 24 hours in the future")
        except ParseError:
            raise ValidationError(
                "datetime format is invalid. It must be a valid ISO8601 date time format, "
                "https://en.wikipedia.org/wiki/ISO_8601"
            )
    return True


@format_checker.checks("datetime_schedule_job", raises=ValidationError)
def validate_schema_date_for_job(instance):
    max_hours = current_app.config["JOBS_MAX_SCHEDULE_HOURS_AHEAD"]
    if isinstance(instance, str):
        try:
            dt = iso8601.parse_date(instance).replace(tzinfo=None)
            if dt < datetime.utcnow():
                raise ValidationError("datetime cannot be in the past")
            if dt > datetime.utcnow() + timedelta(hours=max_hours):
                raise ValidationError(f"datetime can only be up to {max_hours} hours in the future")
        except ParseError:
            raise ValidationError(
                "datetime format is invalid. It must be a valid ISO8601 date time format, "
                "https://en.wikipedia.org/wiki/ISO_8601"
            )
    return True


def validate(json_to_validate, schema):
    validator = Draft7Validator(schema, format_checker=format_checker)
    errors = list(validator.iter_errors(json_to_validate))
    if errors.__len__() > 0:
        raise ValidationError(build_error_message(errors))
    if json_to_validate.get("personalisation", None):
        json_to_validate["personalisation"], errors = validate_personalisation_and_decode_files(
            json_to_validate.get("personalisation", {})
        )
        if errors.__len__() > 0:
            error_message = json.dumps({"status_code": 400, "errors": errors})
            raise ValidationError(error_message)
    return json_to_validate


def build_error_message(errors):
    fields = []
    for e in errors:
        field = (
            "{} {}".format(e.path[0], e.schema["validationMessage"]) if "validationMessage" in e.schema else __format_message(e)
        )
        fields.append({"error": "ValidationError", "message": field})
    message = {"status_code": 400, "errors": unique_errors(fields)}

    return json.dumps(message)


def unique_errors(dups):
    unique = []
    for x in dups:
        if x not in unique:
            unique.append(x)
    return unique


def __format_message(e):
    def get_path(e):
        error_path = None
        try:
            error_path = e.path.popleft()
            # no need to catch IndexError exception explicity as
            # error_path is None if e.path has no items
        finally:
            return error_path

    def get_error_message(e):
        # e.cause is an exception (such as InvalidPhoneError). if it's not present it was a standard jsonschema error
        # such as a required field not being present
        error_message = str(e.cause) if e.cause else e.message
        return error_message.replace("'", "")

    path = get_path(e)
    message = get_error_message(e)
    if path:
        return "{} {}".format(path, message)
    else:
        return "{}".format(message)
