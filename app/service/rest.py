import itertools
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from flask import current_app, Blueprint, jsonify, request
from flask.wrappers import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, DataError
from sqlalchemy.orm.exc import NoResultFound

from app import db
from app.authentication.auth import requires_admin_auth, requires_admin_auth_or_user_in_service
from app.constants import SECRET_TYPE_DEFAULT, SECRET_TYPE_UUID
from app.dao.api_key_dao import (
    get_model_api_key,
    save_model_api_key,
    get_model_api_keys,
    get_unsigned_secret,
    expire_api_key,
)
from app.dao.fact_notification_status_dao import (
    fetch_notification_status_for_service_for_today_and_7_previous_days,
    fetch_stats_for_all_services_by_date_range,
)
from app.dao.services_dao import (
    dao_fetch_all_services,
    dao_fetch_all_services_by_user,
    dao_fetch_service_by_id,
    dao_fetch_todays_stats_for_service,
    dao_fetch_todays_stats_for_all_services,
    dao_update_service,
)
from app.errors import InvalidRequest, register_errors
from app.models import (
    Service,
    EmailBranding,
)
from app.service import statistics
from app.service.sender import send_notification_to_service_users
from app.schemas import (
    service_schema,
    api_key_schema,
    detailed_service_schema,
)

CAN_T_BE_EMPTY_ERROR_MESSAGE = "Can't be empty"

service_blueprint = Blueprint('service', __name__)

register_errors(service_blueprint)


@service_blueprint.errorhandler(IntegrityError)
def handle_integrity_error(exc):
    """
    Handle integrity errors caused by the unique constraint on ix_organisation_name
    """

    if any(
        'duplicate key value violates unique constraint "{}"'.format(constraint) in str(exc)
        for constraint in {'services_name_key', 'services_email_from_key'}
    ):
        return jsonify(
            result='error',
            message={
                'name': ["Duplicate service name '{}'".format(exc.params.get('name', exc.params.get('email_from', '')))]
            },
        ), 400
    current_app.logger.exception(exc)
    return jsonify(result='error', message='Internal server error'), 500


@service_blueprint.route('', methods=['GET'])
@requires_admin_auth()
def get_services():
    only_active = request.args.get('only_active') == 'True'
    detailed = request.args.get('detailed') == 'True'
    user_id = request.args.get('user_id', None)
    include_from_test_key = request.args.get('include_from_test_key', 'True') != 'False'

    # If start and end date are not set, we are expecting today's stats.
    today = str(datetime.utcnow().date())

    start_date = datetime.strptime(request.args.get('start_date', today), '%Y-%m-%d').date()
    end_date = datetime.strptime(request.args.get('end_date', today), '%Y-%m-%d').date()

    if user_id:
        services = dao_fetch_all_services_by_user(user_id, only_active)
    elif detailed:
        result = jsonify(
            data=get_detailed_services(
                start_date=start_date,
                end_date=end_date,
                only_active=only_active,
                include_from_test_key=include_from_test_key,
            )
        )
        return result
    else:
        services = dao_fetch_all_services(only_active)
    data = service_schema.dump(services, many=True)
    return jsonify(data=data)


@service_blueprint.route('/<uuid:service_id>', methods=['GET'])
@requires_admin_auth_or_user_in_service()
def get_service_by_id(service_id):
    if request.args.get('detailed') == 'True':
        data = get_detailed_service(service_id, today_only=request.args.get('today_only') == 'True')
    else:
        fetched = dao_fetch_service_by_id(service_id)

        data = service_schema.dump(fetched)
    return jsonify(data=data)


@service_blueprint.route('/<uuid:service_id>/statistics')
@requires_admin_auth()
def get_service_notification_statistics(service_id):
    return jsonify(
        data=get_service_statistics(
            service_id, request.args.get('today_only') == 'True', int(request.args.get('limit_days', 7))
        )
    )


@service_blueprint.route('/<uuid:service_id>', methods=['POST'])
@requires_admin_auth()
def update_service(service_id):
    req_json = request.get_json()

    fetched_service = dao_fetch_service_by_id(service_id)
    # Capture the status change here as Marshmallow changes this later
    service_going_live = fetched_service.restricted and not req_json.get('restricted', True)
    current_data = service_schema.dump(fetched_service)
    current_data.update(request.get_json())

    service = service_schema.load(current_data)

    if 'email_branding' in req_json:
        email_branding_id = req_json['email_branding']
        service.email_branding = None if not email_branding_id else db.session.get(EmailBranding, email_branding_id)

    dao_update_service(service)

    if service_going_live:
        send_notification_to_service_users(
            service_id=service_id,
            template_id=current_app.config['SERVICE_NOW_LIVE_TEMPLATE_ID'],
            personalisation={
                'service_name': current_data['name'],
                'message_limit': '{:,}'.format(current_data['message_limit']),
            },
            include_user_fields=['name'],
        )

    return jsonify(data=service_schema.dump(fetched_service)), 200


def get_secret_generator(secret_type: str | None):
    """Get the appropriate secret generator function based on secret type.

    Args:
        secret_type (str | None): The type of secret to generate. Currently supports 'uuid', 'default', or None.

    Returns:
        Callable[[], str] | None: Secret generator function or None for default behavior.
    """
    if secret_type == SECRET_TYPE_UUID:  # nosec B105

        def uuid_secret_generator():
            return str(uuid4())

        return uuid_secret_generator

    if secret_type == SECRET_TYPE_DEFAULT:  # nosec B105

        def default_secret_generator():
            import secrets

            return secrets.token_urlsafe(64)

        return default_secret_generator

    return None


@service_blueprint.route('/<uuid:service_id>/api-key', methods=['POST'])
@requires_admin_auth()
def create_api_key(service_id: UUID) -> tuple[Response, Literal[201, 400]]:
    """Create API key for the given service.

    Args:
        service_id (UUID): The id of the service the api key is being added to.

    Returns:
        tuple[Response, Literal[201, 400]]:
        - The response includes the unencrypted key and a 201 response if successful.

    Raises:
        InvalidRequest: 400 Bad Request
        - If unsuccessful for a variety of reasons a usefull error message is provided in the json response body.
    """
    err_msg = 'Could not create requested API key.'

    fetched_service = dao_fetch_service_by_id(service_id=service_id)

    try:
        request_data = request.get_json()
        valid_api_key = api_key_schema.load(request_data)
    except DataError:
        err_msg += ' DataError, ensure created_by user id is a valid uuid'
        current_app.logger.exception(err_msg)
        raise InvalidRequest(err_msg, 400)

    valid_api_key.service = fetched_service
    valid_api_key.expiry_date = datetime.utcnow() + timedelta(days=180)

    # Determine the secret generator function based on secret_type
    secret_type = request_data.get('secret_type') if request_data else None
    secret_generator = get_secret_generator(secret_type)

    try:
        save_model_api_key(valid_api_key, secret_generator=secret_generator)
    except IntegrityError:
        err_msg += ' DB IntegrityError, ensure created_by id is valid and key_type is one of [normal, team, test]'
        current_app.logger.exception(err_msg)
        raise InvalidRequest(err_msg, 400)

    unsigned_api_key = get_unsigned_secret(valid_api_key.id)

    return jsonify(data=unsigned_api_key), 201


@service_blueprint.route('/<uuid:service_id>/api-key/revoke/<uuid:api_key_id>', methods=['POST'])
@requires_admin_auth()
def revoke_api_key(
    service_id: UUID,
    api_key_id: UUID,
) -> tuple[Response, Literal[202, 404]]:
    """Revokes the API key for the given service and key id.

    Args:
        service_id (UUID): The id of the service to which the soon to be revoked key belongs
        api_key_id (UUID): The id of the key to revoke

    Returns:
        tuple[Response, Literal[202, 404]]: 202 Accepted
        - If the requested api key was found and revoked.

    Raises:
        InvalidRequest: 404 NoResultsFound
        - If the service or key is not found.
    """
    try:
        expire_api_key(service_id=service_id, api_key_id=api_key_id)
    except NoResultFound:
        error_message = f'No valid API key found for service {service_id} with id {api_key_id}'
        raise InvalidRequest(error_message, status_code=404)
    return jsonify(), 202


@service_blueprint.route('/<uuid:service_id>/api-keys', methods=['GET'])
@service_blueprint.route('/<uuid:service_id>/api-keys/<uuid:key_id>', methods=['GET'])
@requires_admin_auth()
def get_api_keys(
    service_id: UUID,
    key_id: UUID | None = None,
) -> tuple[Response, Literal[200, 404]]:
    """Returns a list of api keys from the given service.

    Args:
        service_id (UUID): The uuid of the service from which to pull keys
        key_id (UUID): The uuid of the key to lookup

    Params:
        include_revoked: Including this param will return all keys, including revoked ones. By default, returns only
        non-revoked keys.

    Returns:
        tuple[Response, Literal[200, 404]]: 200 OK
        - Returns json list of API keys for the given service, or a list with the indicated key if a key_id is included.

    Raises:
        InvalidRequest: 404 NoResultsFound
        - If there are no valid API keys for the requested service, or the requested service id does not exist.
    """
    include_revoked = request.args.get('include_revoked', 'f')
    include_revoked = str(include_revoked).lower()
    if include_revoked not in ('true', 't', 'false', 'f'):
        raise InvalidRequest('Invalid value for include_revoked', status_code=400)
    include_revoked = include_revoked in ('true', 't')

    dao_fetch_service_by_id(service_id=service_id)

    try:
        if key_id:
            api_keys = [get_model_api_key(key_id=key_id)]
        else:
            api_keys = get_model_api_keys(service_id=service_id, include_revoked=include_revoked)
    except NoResultFound:
        error = f'No valid API key found for service {service_id}'
        raise InvalidRequest(error, status_code=404)

    return jsonify(apiKeys=api_key_schema.dump(api_keys, many=True)), 200


# This is placeholder get method until more thought
# goes into how we want to fetch and view various items in history
# tables. This is so product owner can pass stories as done.
@service_blueprint.route('/<uuid:service_id>/history', methods=['GET'])
@requires_admin_auth()
def get_service_history(service_id):
    from app.models import ApiKey, TemplateHistory
    from app.schemas import service_history_schema, api_key_history_schema, template_history_schema

    service_history_model = Service.get_history_model()
    stmt = select(service_history_model).where(service_history_model.id == service_id)
    service_history = db.session.scalars(stmt).all()

    service_data = service_history_schema.dump(service_history, many=True)

    api_key_history_model = ApiKey.get_history_model()
    stmt = select(api_key_history_model).where(api_key_history_model.service_id == service_id)
    api_key_history = db.session.scalars(stmt).all()

    api_keys_data = api_key_history_schema.dump(api_key_history, many=True)

    stmt = select(TemplateHistory).where(TemplateHistory.service_id == service_id)
    template_history = db.session.scalars(stmt).all()

    template_data = template_history_schema.dump(template_history, many=True)

    data = {
        'service_history': service_data,
        'api_key_history': api_keys_data,
        'template_history': template_data,
        'events': [],
    }

    return jsonify(data=data)


def get_detailed_service(
    service_id,
    today_only=False,
):
    service = dao_fetch_service_by_id(service_id)

    service.statistics = get_service_statistics(service_id, today_only)
    return detailed_service_schema.dump(service)


def get_service_statistics(
    service_id,
    today_only,
    limit_days=7,
):
    # today_only flag is used by the send page to work out if the service will exceed their daily usage by sending a job
    if today_only:
        stats = dao_fetch_todays_stats_for_service(service_id)
    else:
        stats = fetch_notification_status_for_service_for_today_and_7_previous_days(service_id, limit_days=limit_days)

    return statistics.format_statistics(stats)


def get_detailed_services(
    start_date,
    end_date,
    only_active=False,
    include_from_test_key=True,
):
    if start_date == datetime.utcnow().date():
        stats = dao_fetch_todays_stats_for_all_services(
            include_from_test_key=include_from_test_key, only_active=only_active
        )
    else:
        stats = fetch_stats_for_all_services_by_date_range(
            start_date=start_date,
            end_date=end_date,
            include_from_test_key=include_from_test_key,
        )
    results = []
    for service_id, rows in itertools.groupby(stats, lambda x: x.service_id):
        rows = list(rows)
        s = statistics.format_statistics(rows)
        results.append(
            {
                'id': str(rows[0].service_id),
                'name': rows[0].name,
                'notification_type': rows[0].notification_type,
                'research_mode': rows[0].research_mode,
                'restricted': rows[0].restricted,
                'active': rows[0].active,
                'created_at': rows[0].created_at,
                'statistics': s,
            }
        )
    return results
