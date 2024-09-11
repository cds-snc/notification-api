import pytest
from marshmallow import ValidationError
from sqlalchemy import desc, select

from app.dao.provider_details_dao import dao_update_provider_details
from app.models import EMAIL_TYPE, SES_PROVIDER, ProviderDetails, ProviderDetailsHistory


def test_notification_schema_ignores_absent_api_key(sample_notification, sample_template):
    from app.schemas import notification_with_template_schema

    notification = sample_notification(template=sample_template())
    notification.api_key = None
    data = notification_with_template_schema.dump(notification)

    assert data['key_name'] is None


def test_notification_schema_adds_api_key_name(sample_api_key, sample_notification):
    from app.schemas import notification_with_template_schema

    notification = sample_notification()
    api_key = sample_api_key(service=notification.service, key_name='Test key')
    notification.api_key = api_key

    data = notification_with_template_schema.dump(notification)
    assert data['key_name'] == 'Test key'


@pytest.mark.parametrize(
    'schema_name',
    [
        'notification_with_template_schema',
        'notification_schema',
        'notification_with_template_schema',
        'notification_with_personalisation_schema',
    ],
)
def test_notification_schema_has_correct_status(sample_notification, schema_name):
    notification = sample_notification()
    from app import schemas

    data = getattr(schemas, schema_name).dump(notification)

    assert data['status'] == notification.status


@pytest.mark.parametrize(
    'user_attribute, user_value',
    [
        ('name', 'New User'),
        ('email_address', 'newuser@mail.com'),
        ('mobile_number', '+16502532222'),
        ('blocked', False),
    ],
)
def test_user_update_schema_accepts_valid_attribute_pairs(user_attribute, user_value):
    update_dict = {user_attribute: user_value}
    from app.schemas import user_update_schema_load_json

    data = user_update_schema_load_json.load(update_dict)


@pytest.mark.parametrize(
    'user_attribute, user_value',
    [('name', None), ('name', ''), ('email_address', 'bademail@...com'), ('mobile_number', '+44077009')],
)
def test_user_update_schema_rejects_invalid_attribute_pairs(user_attribute, user_value):
    from app.schemas import user_update_schema_load_json

    update_dict = {user_attribute: user_value}

    with pytest.raises(ValidationError):
        data, errors = user_update_schema_load_json.load(update_dict)


@pytest.mark.parametrize(
    'user_attribute',
    [
        'id',
        'updated_at',
        'created_at',
        'user_to_service',
        '_password',
        'verify_codes',
        'logged_in_at',
        'password_changed_at',
        'failed_login_count',
        'state',
        'platform_admin',
    ],
)
def test_user_update_schema_rejects_disallowed_attribute_keys(user_attribute):
    update_dict = {user_attribute: 'not important'}
    from app.schemas import user_update_schema_load_json

    with pytest.raises(ValidationError) as excinfo:
        data, errors = user_update_schema_load_json.load(update_dict)

    assert excinfo.value.messages[user_attribute][0] == 'Unknown field.'


def test_provider_details_schema_returns_user_details(
    mocker,
    notify_db_session,
    sample_user,
    sample_provider,
):
    from app.schemas import provider_details_schema

    user = sample_user()
    provider = sample_provider(created_by=user)

    provider_from_db = notify_db_session.session.get(ProviderDetails, provider.id)
    data = provider_details_schema.dump(provider_from_db)

    assert sorted(data['created_by'].keys()) == sorted(['id', 'email_address', 'name'])


def test_provider_details_history_schema_returns_user_details(
    mocker,
    notify_db_session,
    sample_user,
    sample_provider,
):
    user = sample_user()
    from app.schemas import provider_details_schema

    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=user)
    provider = sample_provider()
    provider.created_by_id = user.id
    data = provider_details_schema.dump(provider)

    dao_update_provider_details(provider)

    stmt = (
        select(ProviderDetailsHistory)
        .where(ProviderDetailsHistory.id == provider.id)
        .order_by(desc(ProviderDetailsHistory.version))
    )

    current_sms_provider_in_history = notify_db_session.session.scalar(stmt)
    data = provider_details_schema.dump(current_sms_provider_in_history)

    assert sorted(data['created_by'].keys()) == sorted(['id', 'email_address', 'name'])


def test_services_schema_includes_providers(
    sample_service,
    sample_provider,
):
    service = sample_service()
    from app.schemas import service_schema

    email_provider = sample_provider(identifier=SES_PROVIDER, notification_type=EMAIL_TYPE)
    sms_provider = sample_provider()  # Defaults to sms - pinpoint
    service.email_provider_id = email_provider.id
    service.sms_provider_id = sms_provider.id

    data = service_schema.dump(service)
    try:
        assert data
        assert data['email_provider_id'] == str(email_provider.id)
        assert data['sms_provider_id'] == str(sms_provider.id)
    finally:
        # Teardown
        service.email_provider_id = None
        service.sms_provider_id = None
