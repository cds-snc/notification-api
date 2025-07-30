from contextlib import suppress
from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import UnsupportedMediaType


pinpoint_v2_blueprint = Blueprint('pinpoint_v2', __name__)


@pinpoint_v2_blueprint.route('/delivery-status/sms/pinpointv2', methods=['POST'])
def handler():
    """
    Temporarily logs request metadata and body for debugging Pinpoint SMS delivery status updates.
    This is placeholder functionality until delivery status handling logic is added

    Returns:
        tuple: JSON response body and HTTP status code 200.
    """
    request_attrs = (
        'method',
        'root_path',
        'path',
        'url_rule',
    )
    logs = [f'{attr.upper()}: {getattr(request, attr, None)}' for attr in request_attrs]

    with suppress(UnsupportedMediaType, Exception):
        logs.append(f'JSON: {request.get_json(silent=True)}')

    headers_string = ', '.join([f'{key}: {value}' for key, value in request.headers.items()])
    logs.append(f'HEADERS: {headers_string}')

    current_app.logger.info('PinpointV2 delivery-status request: %s', ' | '.join(logs))

    return jsonify({'status': 'received'}), 200
