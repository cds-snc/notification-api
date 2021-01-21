from app.dao.provider_details_dao import get_provider_details_by_id
from app.errors import InvalidRequest


def is_provider_valid(provider_id: str, notification_type: str) -> bool:
    provider_details = get_provider_details_by_id(provider_id)
    return (
        provider_details is not None
        and provider_details.active
        and provider_details.notification_type == notification_type
    )


def validate_template_providers(request: dict):
    provider_id = request.get('provider_id')
    template_type = request.get('template_type')

    if not(provider_id is None or is_provider_valid(provider_id, template_type)):
        throw_invalid_request_error(template_type)


def validate_template_provider(provider_id: str, template_type: str):
    if not(provider_id is None or is_provider_valid(provider_id, template_type)):
        throw_invalid_request_error(template_type)


def throw_invalid_request_error(template_type):
    raise InvalidRequest(f'invalid {template_type}_provider_id', status_code=400)
