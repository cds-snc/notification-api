from flask import Blueprint, current_app, jsonify, request

from app.authentication.auth import \
    create_validator_for_user_in_service_or_admin
from app.dao.dao_utils import dao_rollback
from app.dao.service_whitelist_dao import (
    dao_add_and_commit_whitelisted_contacts, dao_fetch_service_whitelist,
    dao_remove_service_whitelist)
from app.dao.services_dao import dao_fetch_service_by_id
from app.errors import InvalidRequest, register_errors, invalid_data_v2
from app.models import (EMAIL_TYPE, MANAGE_SETTINGS, MOBILE_TYPE,
                        ServiceWhitelist)
from app.schema_validation import validate

from .service_whitelist_schema import update_service_whitelist_request


def _validate_service_exists():
    # This will throw NoResultFound Exception which will be turned into 404 response by global error hanlders
    dao_fetch_service_by_id(request.view_args.get('service_id'))


service_whitelist_blueprint = Blueprint(
    'service_whitelist',
    __name__,
    url_prefix='/service/<uuid:service_id>/whitelist'
)
service_whitelist_blueprint.before_request(
    create_validator_for_user_in_service_or_admin(required_permission=MANAGE_SETTINGS)
)
service_whitelist_blueprint.before_request(_validate_service_exists)

register_errors(service_whitelist_blueprint)
# Override default InvalidRequest error handler to return v2 response
service_whitelist_blueprint.register_error_handler(InvalidRequest, invalid_data_v2)


@service_whitelist_blueprint.route('', methods=['GET'])
def get_whitelist(service_id):
    whitelist = dao_fetch_service_whitelist(service_id)
    return jsonify(
        email_addresses=[item.recipient for item in whitelist
                         if item.recipient_type == EMAIL_TYPE],
        phone_numbers=[item.recipient for item in whitelist
                       if item.recipient_type == MOBILE_TYPE]
    )


@service_whitelist_blueprint.route('', methods=['PUT'])
def update_whitelist(service_id):
    request_json = validate(request.get_json(), update_service_whitelist_request)

    # doesn't commit so if there are any errors, we preserve old values in db
    dao_remove_service_whitelist(service_id)
    try:
        whitelist_objs = _get_whitelist_objects(service_id, request_json)
    except ValueError as e:
        current_app.logger.exception(e)
        dao_rollback()
        msg = '{} is not a valid email address or phone number'.format(str(e))
        raise InvalidRequest(msg, 400)
    else:
        dao_add_and_commit_whitelisted_contacts(whitelist_objs)
        return '', 204


def _get_recipients_from_request(request_json, key, type):
    return [(type, recipient) for recipient in request_json.get(key)]


def _get_whitelist_objects(service_id, request_json):
    return [
        ServiceWhitelist.from_string(service_id, type, recipient)
        for type, recipient in (
            _get_recipients_from_request(request_json, 'phone_numbers', MOBILE_TYPE)
            + _get_recipients_from_request(request_json, 'email_addresses', EMAIL_TYPE)
        )
    ]
