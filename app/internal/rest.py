"""
Flask Blueprint for internal endpoints of the form /internal/<generic>.
  - GET requests return a string with the full path of the request and a 200 status code.
  - POST requests return a JSON object with the request data and a 200 status code.

Logging is performed for the following request attributes:
    - headers
    - method
    - root_path
    - path
    - query_string
    - json
    - url_rule
    - trace_id
"""

import time
from werkzeug.exceptions import UnsupportedMediaType
from contextlib import suppress
from flask import Blueprint, current_app, jsonify, request


internal_blueprint = Blueprint('internal', __name__, url_prefix='/internal')


@internal_blueprint.route('/<generic>', methods=['POST', 'GET'])
def handler(generic):
    """
    Logs the request and returns a 200 response.

    Args:
        generic (str): A generic endpoint from the URL.

    Returns:
        tuple: A tuple containing the response body and status code. For GET requests, the response body is
          a string with the endpoint. For POST requests, the response body is a JSON object with the request
          data. The status code is always 200.

    """
    status_code = 200
    request_attrs = (
        'method',
        'root_path',
        'path',
        'query_string',
        'url_rule',
        'trace_id',
    )
    logs = [f'{attr.upper()}: {getattr(request, attr)}' for attr in request_attrs if hasattr(request, attr)]
    with suppress(UnsupportedMediaType):
        logs.append(f'JSON: {request.json}')
    headers_string = ', '.join([f'{key}: {value}' for key, value in request.headers.items()])
    logs.append(f'HEADERS: {headers_string}')
    current_app.logger.info('Generic Internal Request: %s', ' | '.join(logs))
    if request.method == 'GET':
        response_body = jsonify({generic: f'GET request received for endpoint {request.full_path}'})
    else:
        response_body = {generic: request.json}

    return response_body, status_code


@internal_blueprint.route('/502', methods=['POST', 'GET'])
def throw_502():
    """
    Returns a 502 Bad Gateway response for testing purposes.

    Returns:
        Response: A JSON response with 'result' set to 'error' and 'message',
        along with a 502 status code.
    """
    return jsonify(result='error', message='hello world'), 502


@internal_blueprint.route('/sleep', methods=['POST', 'GET'])
def sleep():
    """
    Simulates a delayed response by sleeping for 30 seconds.

    Returns:
        Response: A JSON response indicating success, with a 'message' stating the sleep duration,
          along with a 201 status code.
    """
    time.sleep(30)
    return jsonify(result='success', message='slept for 30s'), 201
