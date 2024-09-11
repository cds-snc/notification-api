from app.models import MANAGE_SETTINGS, QUEUE_CHANNEL_TYPE
from app.authentication.auth import AuthError, create_validator_for_user_in_service_or_admin
from flask import (
    Blueprint,
    jsonify,
    request,
)
from flask_jwt_extended import current_user
from sqlalchemy.exc import SQLAlchemyError

from app.dao.service_callback_api_dao import (
    query_service_callback,
    save_service_callback_api,
    delete_service_callback_api,
    store_service_callback_api,
    get_service_callbacks,
)
from app.errors import register_errors
from app.schema_validation import validate
from app.schemas import service_callback_api_schema
from app.service.service_callback_api_schema import (
    update_service_callback_api_request_schema,
    create_service_callback_api_request_schema,
)

service_callback_blueprint = Blueprint('service_callback', __name__, url_prefix='/service/<uuid:service_id>/callback')
service_callback_blueprint.before_request(
    create_validator_for_user_in_service_or_admin(required_permission=MANAGE_SETTINGS)
)

register_errors(service_callback_blueprint)


@service_callback_blueprint.route('', methods=['GET'])
def fetch_service_callbacks(service_id):
    service_callbacks = get_service_callbacks(service_id)
    return jsonify(data=service_callback_api_schema.dump(service_callbacks, many=True)), 200


@service_callback_blueprint.route('/<uuid:callback_id>', methods=['GET'])
def fetch_service_callback(
    service_id,
    callback_id,
):
    service_callback = query_service_callback(service_id, callback_id)

    return jsonify(data=service_callback_api_schema.dump(service_callback)), 200


@service_callback_blueprint.route('', methods=['POST'])
def create_service_callback(service_id):
    data = request.get_json()
    data['service_id'] = service_id
    data['updated_by_id'] = current_user.id
    validate(data, create_service_callback_api_request_schema)
    require_admin_for_queue_callback(data)

    new_service_callback = service_callback_api_schema.load(data)

    try:
        save_service_callback_api(new_service_callback)
    except SQLAlchemyError as e:
        return handle_sql_error(e, 'service_callback')

    return jsonify(data=service_callback_api_schema.dump(new_service_callback)), 201


@service_callback_blueprint.route('/<uuid:callback_id>', methods=['POST'])
def update_service_callback(
    service_id,
    callback_id,
):
    data = request.get_json()
    data['service_id'] = service_id
    data['updated_by_id'] = current_user.id

    validate(data, update_service_callback_api_request_schema)
    current_service_callback = query_service_callback(service_id, callback_id)

    require_admin_for_queue_callback({**service_callback_api_schema.dump(current_service_callback), **data})

    updated_service_callback = service_callback_api_schema.load(
        data, instance=current_service_callback, transient=True, partial=True
    )
    store_service_callback_api(updated_service_callback)

    return jsonify(data=service_callback_api_schema.dump(updated_service_callback)), 200


@service_callback_blueprint.route('/<uuid:callback_id>', methods=['DELETE'])
def remove_service_callback(
    service_id,
    callback_id,
):
    callback = query_service_callback(service_id, callback_id)

    delete_service_callback_api(callback)
    return '', 204


def handle_sql_error(
    e,
    table_name,
):
    if (
        hasattr(e, 'orig')
        and hasattr(e.orig, 'pgerror')
        and e.orig.pgerror
        and ('duplicate key value violates unique constraint "ix_{}_service_id"'.format(table_name) in e.orig.pgerror)
    ):
        return jsonify(
            result='error', message={'name': ['You can only have one URL and bearer token for your service.']}
        ), 400
    elif (
        hasattr(e, 'orig')
        and hasattr(e.orig, 'pgerror')
        and e.orig.pgerror
        and (
            'insert or update on table "{0}" violates ' 'foreign key constraint "{0}_api_service_id_fkey"'.format(
                table_name
            )
            in e.orig.pgerror
        )
    ):
        return jsonify(result='error', message='No result found'), 404
    else:
        raise e


def require_admin_for_queue_callback(data):
    if (
        'callback_channel' in data
        and data['callback_channel'] == QUEUE_CHANNEL_TYPE
        and not current_user.platform_admin
    ):
        raise AuthError(f'User does not have permissions to create callbacks of channel type {QUEUE_CHANNEL_TYPE}', 403)
