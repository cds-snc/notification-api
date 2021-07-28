from flask import (
    Blueprint,
    jsonify,
    request,
)
from sqlalchemy.exc import SQLAlchemyError

from app.errors import (
    register_errors,
    InvalidRequest
)
from app.models import (
    DELIVERY_STATUS_CALLBACK_TYPE
)
from app.schema_validation import validate
from app.schemas import service_callback_api_schema
from app.service.service_callback_api_schema import (
    update_service_callback_api_request_schema,
    create_service_callback_api_request_schema
)
from app.dao.service_callback_api_dao import (
    save_service_callback_api,
    get_service_callback,
    delete_service_callback_api, store_service_callback_api, get_service_callbacks
)

service_callback_blueprint = Blueprint('service_callback', __name__, url_prefix='/service/<uuid:service_id>')

register_errors(service_callback_blueprint)


@service_callback_blueprint.route('/delivery-receipt-api', methods=['POST'])
def create_service_callback_api(service_id):
    data = request.get_json()

    validate(data, create_service_callback_api_request_schema)

    data["service_id"] = service_id
    data["callback_type"] = DELIVERY_STATUS_CALLBACK_TYPE
    new_service_callback_api = service_callback_api_schema.load(data).data

    try:
        save_service_callback_api(new_service_callback_api)
    except SQLAlchemyError as e:
        return handle_sql_error(e, 'service_callback')

    return jsonify(data=service_callback_api_schema.dump(new_service_callback_api).data), 201


@service_callback_blueprint.route('/delivery-receipt-api/<uuid:callback_api_id>', methods=['POST'])
def update_service_callback_api(service_id, callback_api_id):
    request_json = request.get_json()
    request_json["service_id"] = service_id

    validate(request_json, update_service_callback_api_request_schema)

    current_service_callback_api = get_service_callback(callback_api_id)

    updated_service_callback_api = service_callback_api_schema.load(
        request_json, instance=current_service_callback_api, transient=True, partial=True
    ).data
    store_service_callback_api(updated_service_callback_api)

    return jsonify(data=service_callback_api_schema.dump(updated_service_callback_api).data), 200


@service_callback_blueprint.route('/delivery-receipt-api/<uuid:callback_api_id>', methods=["GET"])
def fetch_service_callback_api(service_id, callback_api_id):  # noqa
    service_callback_api = get_service_callback(callback_api_id)

    return jsonify(data=service_callback_api_schema.dump(service_callback_api).data), 200


@service_callback_blueprint.route('/callback', methods=['GET'])
def fetch_service_callbacks(service_id):
    service_callbacks = get_service_callbacks(service_id)
    return jsonify(data=service_callback_api_schema.dump(service_callbacks, many=True).data), 200


@service_callback_blueprint.route('/callback', methods=['POST'])
def create_service_callback(service_id):
    data = request.get_json()

    data["service_id"] = service_id

    validate(data, create_service_callback_api_request_schema)

    new_service_callback_api = service_callback_api_schema.load(data).data

    try:
        save_service_callback_api(new_service_callback_api)
    except SQLAlchemyError as e:
        return handle_sql_error(e, 'service_callback')

    return jsonify(data=service_callback_api_schema.dump(new_service_callback_api).data), 201


@service_callback_blueprint.route('/delivery-receipt-api/<uuid:callback_api_id>', methods=['DELETE'])
def remove_service_callback_api(service_id, callback_api_id):  # noqa
    callback_api = get_service_callback(callback_api_id)

    if not callback_api:
        error = 'Service delivery receipt callback API not found'
        raise InvalidRequest(error, status_code=404)

    delete_service_callback_api(callback_api)
    return '', 204


def handle_sql_error(e, table_name):
    if hasattr(e, 'orig') and hasattr(e.orig, 'pgerror') and e.orig.pgerror \
            and ('duplicate key value violates unique constraint "ix_{}_service_id"'.format(table_name)
                 in e.orig.pgerror):
        return jsonify(
            result='error',
            message={'name': ["You can only have one URL and bearer token for your service."]}
        ), 400
    elif hasattr(e, 'orig') and hasattr(e.orig, 'pgerror') and e.orig.pgerror \
            and ('insert or update on table "{0}" violates '
                 'foreign key constraint "{0}_api_service_id_fkey"'.format(table_name)
                 in e.orig.pgerror):
        return jsonify(result='error', message="No result found"), 404
    else:
        raise e
