import pytest
from flask import json
from freezegun import freeze_time
from uuid import uuid4
from werkzeug.http import http_date

from tests import create_admin_authorization_header


def test_get_provider_details_returns_information_about_providers(client, notify_db, mocked_provider_stats, mocker):
    mocker.patch('app.provider_details.rest.dao_get_provider_stats', return_value=mocked_provider_stats)
    response = client.get('/provider-details', headers=[create_admin_authorization_header()])
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


def test_get_provider_details_by_id(
    client,
    sample_provider,
):
    # Populate DB with a provider
    sample_provider(str(uuid4()))

    # Leaving all these get calls for now, even though we could reference the sample_provider's return
    response = client.get('/provider-details', headers=[create_admin_authorization_header()])
    json_resp = json.loads(response.get_data(as_text=True))['provider_details']

    provider_resp = client.get(
        '/provider-details/{}'.format(json_resp[0]['id']), headers=[create_admin_authorization_header()]
    )

    provider = json.loads(provider_resp.get_data(as_text=True))['provider_details']
    assert provider['identifier'] == json_resp[0]['identifier']


@freeze_time('2018-06-28 12:00')
def test_get_provider_contains_correct_fields(
    client,
    sample_ft_billing,
    sample_provider,
    sample_template,
):
    template = sample_template()
    sample_ft_billing('2018-06-01', 'sms', template, template.service, provider='mmg', billable_unit=1)

    sample_provider()
    response = client.get('/provider-details', headers=[create_admin_authorization_header()])
    json_resp = json.loads(response.get_data(as_text=True))['provider_details']
    allowed_keys = {
        'id',
        'created_by_name',
        'display_name',
        'identifier',
        'priority',
        'notification_type',
        'active',
        'updated_at',
        'supports_international',
        'load_balancing_weight',
        'current_month_billable_sms',
    }
    assert allowed_keys == set(json_resp[0].keys())


@pytest.mark.serial
class TestUpdate:
    def test_should_be_able_to_update_priority(
        self,
        client,
        sample_provider,
        restore_provider_details,
    ):
        provider = sample_provider()

        update_resp = client.post(
            '/provider-details/{}'.format(provider.id),
            headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
            data=json.dumps({'priority': 5}),
        )
        assert update_resp.status_code == 200
        update_json = json.loads(update_resp.get_data(as_text=True))['provider_details']
        assert update_json['identifier'] == provider.identifier
        assert update_json['priority'] == 5
        assert provider.priority == 5

    def test_should_be_able_to_update_status(
        self,
        client,
        sample_provider,
        restore_provider_details,
    ):
        provider = sample_provider()

        update_resp_1 = client.post(
            '/provider-details/{}'.format(provider.id),
            headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
            data=json.dumps({'active': False}),
        )
        assert update_resp_1.status_code == 200
        update_resp_1 = json.loads(update_resp_1.get_data(as_text=True))['provider_details']
        assert update_resp_1['identifier'] == provider.identifier
        assert not update_resp_1['active']
        assert not provider.active

    @pytest.mark.parametrize('field,value', [('identifier', 'new'), ('version', 7), ('updated_at', None)])
    def test_should_not_be_able_to_update_disallowed_fields(
        self,
        client,
        sample_provider,
        restore_provider_details,
        field,
        value,
    ):
        provider = sample_provider()

        resp = client.post(
            '/provider-details/{}'.format(provider.id),
            headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
            data=json.dumps({field: value}),
        )
        resp_json = json.loads(resp.get_data(as_text=True))

        assert resp_json['message'][field][0] == 'Not permitted to be updated'
        assert resp_json['result'] == 'error'
        assert resp.status_code == 400

    def test_update_provider_should_store_user_id(
        self,
        client,
        sample_provider,
        sample_user,
        restore_provider_details,
    ):
        user_start = sample_user()
        user_update = sample_user()
        provider = sample_provider(created_by=user_start)

        update_resp_1 = client.post(
            '/provider-details/{}'.format(provider.id),
            headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
            data=json.dumps({'created_by': user_update.id, 'active': False}),
        )
        assert update_resp_1.status_code == 200
        update_resp_1 = json.loads(update_resp_1.get_data(as_text=True))['provider_details']
        assert update_resp_1['identifier'] == provider.identifier
        assert not update_resp_1['active']
        assert not provider.active

    def test_should_be_able_to_update_load_balancing_weight(
        self,
        client,
        sample_provider,
        restore_provider_details,
    ):
        provider = sample_provider()

        update_resp_1 = client.post(
            '/provider-details/{}'.format(provider.id),
            headers=[('Content-Type', 'application/json'), create_admin_authorization_header()],
            data=json.dumps({'load_balancing_weight': 333}),
        )
        assert update_resp_1.status_code == 200
        update_resp_1 = json.loads(update_resp_1.get_data(as_text=True))['provider_details']
        assert update_resp_1['identifier'] == provider.identifier
        assert provider.load_balancing_weight == 333


def test_get_provider_versions_contains_correct_fields(
    client,
    sample_provider,
):
    provider = sample_provider()
    response = client.get(
        '/provider-details/{}/versions'.format(provider.id), headers=[create_admin_authorization_header()]
    )

    json_resp = json.loads(response.get_data(as_text=True))['data']
    allowed_keys = {
        'id',
        'created_by',
        'display_name',
        'identifier',
        'load_balancing_weight',
        'priority',
        'notification_type',
        'active',
        'version',
        'updated_at',
        'supports_international',
    }
    assert allowed_keys == set(json_resp[0].keys())
