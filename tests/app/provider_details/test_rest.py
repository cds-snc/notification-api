import pytest
from flask import json
from freezegun import freeze_time
from werkzeug.http import http_date

from app.models import ProviderDetails, ProviderDetailsHistory

from tests import create_authorization_header
from tests.app.db import create_ft_billing


def test_get_provider_details_returns_information_about_providers(client, notify_db, mocked_provider_stats, mocker):
    mocker.patch('app.provider_details.rest.dao_get_provider_stats', return_value=mocked_provider_stats)
    response = client.get(
        '/provider-details',
        headers=[create_authorization_header()]
    )
    assert response.status_code == 200
    json_resp = json.loads(response.get_data(as_text=True))['provider_details']

    assert len(json_resp) == len(mocked_provider_stats)

    for idx, provider in enumerate(mocked_provider_stats):
        assert json_resp[idx]['identifier'] == provider.identifier
        assert json_resp[idx]['display_name'] == provider.display_name
        assert json_resp[idx]['priority'] == provider.priority
        assert json_resp[idx]['notification_type'] == provider.notification_type
        assert json_resp[idx]['active'] == provider.active
        assert json_resp[idx]['updated_at'] == http_date(provider.updated_at)
        assert json_resp[idx]['supports_international'] == provider.supports_international
        assert json_resp[idx]['created_by_name'] == provider.created_by_name
        assert json_resp[idx]['current_month_billable_sms'] == provider.current_month_billable_sms


def test_get_provider_details_by_id(client, notify_db):
    response = client.get(
        '/provider-details',
        headers=[create_authorization_header()]
    )
    json_resp = json.loads(response.get_data(as_text=True))['provider_details']

    provider_resp = client.get(
        '/provider-details/{}'.format(json_resp[0]['id']),
        headers=[create_authorization_header()]
    )

    provider = json.loads(provider_resp.get_data(as_text=True))['provider_details']
    assert provider['identifier'] == json_resp[0]['identifier']


@freeze_time('2018-06-28 12:00')
def test_get_provider_contains_correct_fields(client, sample_service, sample_template):
    create_ft_billing('2018-06-01', 'sms', sample_template, sample_service, provider='mmg', billable_unit=1)

    response = client.get(
        '/provider-details',
        headers=[create_authorization_header()]
    )
    json_resp = json.loads(response.get_data(as_text=True))['provider_details']
    allowed_keys = {
        "id", "created_by_name", "display_name",
        "identifier", "priority", 'notification_type',
        "active", "updated_at", "supports_international",
        "load_balancing_weight",
        "current_month_billable_sms"
    }
    assert allowed_keys == set(json_resp[0].keys())


class TestUpdate:

    def test_should_be_able_to_update_priority(self, client, restore_provider_details):
        provider = ProviderDetails.query.first()

        update_resp = client.post(
            '/provider-details/{}'.format(provider.id),
            headers=[('Content-Type', 'application/json'), create_authorization_header()],
            data=json.dumps({
                'priority': 5
            })
        )
        assert update_resp.status_code == 200
        update_json = json.loads(update_resp.get_data(as_text=True))['provider_details']
        assert update_json['identifier'] == provider.identifier
        assert update_json['priority'] == 5
        assert provider.priority == 5

    def test_should_be_able_to_update_status(self, client, restore_provider_details):
        provider = ProviderDetails.query.first()

        update_resp_1 = client.post(
            '/provider-details/{}'.format(provider.id),
            headers=[('Content-Type', 'application/json'), create_authorization_header()],
            data=json.dumps({
                'active': False
            })
        )
        assert update_resp_1.status_code == 200
        update_resp_1 = json.loads(update_resp_1.get_data(as_text=True))['provider_details']
        assert update_resp_1['identifier'] == provider.identifier
        assert not update_resp_1['active']
        assert not provider.active

    @pytest.mark.parametrize('field,value', [
        ('identifier', 'new'),
        ('version', 7),
        ('updated_at', None)
    ])
    def test_should_not_be_able_to_update_disallowed_fields(self, client, restore_provider_details, field, value):
        provider = ProviderDetails.query.first()

        resp = client.post(
            '/provider-details/{}'.format(provider.id),
            headers=[('Content-Type', 'application/json'), create_authorization_header()],
            data=json.dumps({field: value})
        )
        resp_json = json.loads(resp.get_data(as_text=True))

        assert resp_json['message'][field][0] == 'Not permitted to be updated'
        assert resp_json['result'] == 'error'
        assert resp.status_code == 400

    def test_update_provider_should_store_user_id(self, client, restore_provider_details, sample_user):
        provider = ProviderDetails.query.first()

        update_resp_1 = client.post(
            '/provider-details/{}'.format(provider.id),
            headers=[('Content-Type', 'application/json'), create_authorization_header()],
            data=json.dumps({
                'created_by': sample_user.id,
                'active': False
            })
        )
        assert update_resp_1.status_code == 200
        update_resp_1 = json.loads(update_resp_1.get_data(as_text=True))['provider_details']
        assert update_resp_1['identifier'] == provider.identifier
        assert not update_resp_1['active']
        assert not provider.active

    def test_should_be_able_to_update_load_balancing_weight(self, client, restore_provider_details):
        provider = ProviderDetails.query.first()

        update_resp_1 = client.post(
            '/provider-details/{}'.format(provider.id),
            headers=[('Content-Type', 'application/json'), create_authorization_header()],
            data=json.dumps({
                'load_balancing_weight': 333
            })
        )
        assert update_resp_1.status_code == 200
        update_resp_1 = json.loads(update_resp_1.get_data(as_text=True))['provider_details']
        assert update_resp_1['identifier'] == provider.identifier
        assert provider.load_balancing_weight == 333


def test_get_provider_versions_contains_correct_fields(client, notify_db):
    provider = ProviderDetailsHistory.query.first()
    response = client.get(
        '/provider-details/{}/versions'.format(provider.id),
        headers=[create_authorization_header()]
    )
    json_resp = json.loads(response.get_data(as_text=True))['data']
    allowed_keys = {
        "id", "created_by", "display_name",
        "identifier", "load_balancing_weight", "priority", 'notification_type',
        "active", "version", "updated_at", "supports_international"
    }
    assert allowed_keys == set(json_resp[0].keys())
