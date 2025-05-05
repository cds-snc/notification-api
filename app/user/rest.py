from flask import jsonify, Blueprint, current_app
from sqlalchemy.exc import IntegrityError

from app.dao.users_dao import (
    get_user_by_id,
)
from app.errors import register_errors

user_blueprint = Blueprint('user', __name__)
register_errors(user_blueprint)


@user_blueprint.errorhandler(IntegrityError)
def handle_integrity_error(exc):
    """
    Handle integrity errors caused by the auth type/mobile number check constraint
    """
    if 'ck_users_mobile_number_if_sms_auth' in str(exc):
        # we don't expect this to trip, so still log error
        current_app.logger.exception('Check constraint ck_users_mobile_number_if_sms_auth triggered')
        return jsonify(result='error', message='Mobile number must be set if auth_type is set to sms_auth'), 400

    raise exc


@user_blueprint.route('/<uuid:user_id>', methods=['GET'])
@user_blueprint.route('', methods=['GET'])
def get_user(user_id=None):
    users = get_user_by_id(user_id=user_id)
    result = [x.serialize() for x in users] if isinstance(users, list) else users.serialize()
    return jsonify(data=result)
