import pytest
from flask import json
from uuid import uuid4

from tests.app.db import create_organisation


@pytest.mark.parametrize('path', ['/', '/_status'])
def test_get_status_all_ok(client, path):
    response = client.get(path)
    assert response.status_code == 200
    resp_json = json.loads(response.get_data(as_text=True))
    assert resp_json['status'] == 'ok'
    assert resp_json['db_version']
    assert resp_json['git_commit']
    assert resp_json['build_time']


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_empty_live_service_and_organisation_counts(admin_request):
    assert admin_request.get('status.live_service_and_organisation_counts') == {
        'organisations': 0,
        'services': 0,
    }


@pytest.mark.skip(reason='Endpoint slated for removal. Test not updated.')
def test_populated_live_service_and_organisation_counts(admin_request, sample_service):
    # Org 1 has three real live services and one fake, for a total of 3
    org_1 = create_organisation('org 1')
    live_service_1 = sample_service(service_name=f'1_{uuid4()}')
    live_service_1.organisation = org_1
    live_service_2 = sample_service(service_name=f'2_{uuid4()}')
    live_service_2.organisation = org_1
    live_service_3 = sample_service(service_name=f'3_{uuid4()}')
    live_service_3.organisation = org_1
    fake_live_service_1 = sample_service(service_name=f'f1_{uuid4()}', count_as_live=False)
    fake_live_service_1.organisation = org_1
    inactive_service_1 = sample_service(service_name=f'i1_{uuid4()}', active=False)
    inactive_service_1.organisation = org_1

    # This service isn’t associated to an org, but should still be counted as live
    sample_service(service_name=f'4_{uuid4()}')

    # Org 2 has no real live services
    org_2 = create_organisation('org 2')
    trial_service_1 = sample_service(service_name=f't1_{uuid4()}', restricted=True)
    trial_service_1.organisation = org_2
    fake_live_service_2 = sample_service(service_name=f'f2_{uuid4()}', count_as_live=False)
    fake_live_service_2.organisation = org_2
    inactive_service_2 = sample_service(service_name=f'i2_{uuid4()}', active=False)
    inactive_service_2.organisation = org_2

    # Org 2 has no services at all
    create_organisation('org 3')

    # This service isn’t associated to an org, and should not be counted as live
    # because it’s marked as not counted
    sample_service(service_name=f'f3_{uuid4()}', count_as_live=False)

    # This service isn’t associated to an org, and should not be counted as live
    # because it’s in trial mode
    sample_service(service_name=f't_{uuid4()}', restricted=True)
    sample_service(service_name=f'i_{uuid4()}', restricted=False, active=False)

    assert admin_request.get('status.live_service_and_organisation_counts') == {
        'organisations': 0,  # hardcoded due to being unused
        'services': 4,
    }
