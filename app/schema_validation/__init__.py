import json
from app.notifications.validators import decode_personalisation_files
from datetime import datetime, timedelta
from flask import current_app
from iso8601 import iso8601, ParseError
from jsonschema import Draft7Validator, FormatChecker, ValidationError
from notifications_utils.recipients import (
    InvalidEmailError,
    InvalidPhoneError,
    validate_email_address,
    validate_phone_number,
)
from uuid import UUID

format_checker = FormatChecker()


@format_checker.checks('validate_uuid', raises=Exception)
def validate_uuid(instance):
    if isinstance(instance, str):
        UUID(instance)
    return True


@format_checker.checks('phone_number', raises=InvalidPhoneError)
def validate_schema_phone_number(instance):
    if isinstance(instance, str):
        validate_phone_number(instance, international=True)
    return True


@format_checker.checks('email_address', raises=InvalidEmailError)
def validate_schema_email_address(instance):
    if isinstance(instance, str):
        validate_email_address(instance)
    return True


@format_checker.checks('postage', raises=ValidationError)
def validate_schema_postage(instance):
    if isinstance(instance, str):
        if instance not in ['first', 'second']:
            raise ValidationError('invalid. It must be either first or second.')
    return True


@format_checker.checks('datetime_within_next_day', raises=ValidationError)
def validate_schema_date_with_hour(instance):
    if isinstance(instance, str):
        try:
            dt = iso8601.parse_date(instance).replace(tzinfo=None)
            if dt < datetime.utcnow():
                raise ValidationError('datetime can not be in the past')
            if dt > datetime.utcnow() + timedelta(hours=24):
                raise ValidationError('datetime can only be 24 hours in the future')
        except ParseError:
            raise ValidationError(
                'datetime format is invalid. It must be a valid ISO8601 date time format, '
                'https://en.wikipedia.org/wiki/ISO_8601'
            )
    return True


def validate(
    json_to_validate,
    schema,
):
    validator = Draft7Validator(schema, format_checker=format_checker)
    errors = list(validator.iter_errors(json_to_validate))
    if len(errors) > 0:
        if isinstance(json_to_validate, dict) and 'personalisation' in json_to_validate:
            if isinstance(json_to_validate['personalisation'], str):
                json_to_validate['personalisation'] = '<redacted>'
            elif isinstance(json_to_validate['personalisation'], dict):
                json_to_validate['personalisation'] = {key: '<redacted>' for key in json_to_validate['personalisation']}
        current_app.logger.info('Validation failed for: %s', json_to_validate)
        raise ValidationError(build_error_message(errors))

    # TODO - This assumes that json_to_validate is a dictionary.  It could raise AttributeError.
    if json_to_validate.get('personalisation'):
        json_to_validate['personalisation'], errors = decode_personalisation_files(
            json_to_validate.get('personalisation', {})
        )
        if len(errors) > 0:
            error_message = json.dumps({'status_code': 400, 'errors': errors})
            raise ValidationError(error_message)
    return json_to_validate


def build_error_message(errors):
    fields = []
    for e in errors:
        if 'validationMessage' not in e.schema:
            error_message = __format_message(e)
        else:
            if len(e.path) > 0:
                # a path indicates that we are validating a specific property
                # eg: "template_id" + " is not a valid UUID"
                error_message = f"{e.path[0]} {e.schema['validationMessage']}"
            elif e.validator in e.schema['validationMessage']:
                error_message = e.schema['validationMessage'][e.validator]
            else:
                error_message = __format_message(e)
        fields.append({'error': 'ValidationError', 'message': error_message})
    message = {'status_code': 400, 'errors': unique_errors(fields)}

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
        return error_message.replace("'", '')

    path = get_path(e)
    message = get_error_message(e)
    if path:
        return '{} {}'.format(path, message)
    else:
        return '{}'.format(message)
