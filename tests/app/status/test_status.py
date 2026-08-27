import pytest
from flask import json
from tests.app.db import create_organisation, create_service

WAF_SECRET = "test-waf-secret"
WAF_HEADER = {"waf-secret": WAF_SECRET}


@pytest.mark.parametrize("path", ["/", "/_status"])
def test_get_status_all_ok(client, notify_db_session, path):
    response = client.get(path)
    assert response.status_code == 200
    resp_json = json.loads(response.get_data(as_text=True))
    assert resp_json["status"] == "ok"
    assert resp_json["db_version"]
    assert resp_json["commit_sha"]
    assert resp_json["build_time"]
    assert resp_json["current_time_utc"]


def test_empty_live_service_and_organisation_counts(admin_request):
    assert admin_request.get("status.live_service_and_organisation_counts") == {
        "organisations": 0,
        "services": 0,
    }


def test_populated_live_service_and_organisation_counts(admin_request):
    # Org 1 has three real live services and one fake, for a total of 3
    org_1 = create_organisation("org 1")
    live_service_1 = create_service(service_name="1")
    live_service_1.organisation = org_1
    live_service_2 = create_service(service_name="2")
    live_service_2.organisation = org_1
    live_service_3 = create_service(service_name="3")
    live_service_3.organisation = org_1
    fake_live_service_1 = create_service(service_name="f1", count_as_live=False)
    fake_live_service_1.organisation = org_1
    inactive_service_1 = create_service(service_name="i1", active=False)
    inactive_service_1.organisation = org_1

    # This service isn’t associated to an org, but should still be counted as live
    create_service(service_name="4")

    # Org 2 has no real live services
    org_2 = create_organisation("org 2")
    trial_service_1 = create_service(service_name="t1", restricted=True)
    trial_service_1.organisation = org_2
    fake_live_service_2 = create_service(service_name="f2", count_as_live=False)
    fake_live_service_2.organisation = org_2
    inactive_service_2 = create_service(service_name="i2", active=False)
    inactive_service_2.organisation = org_2

    # Org 2 has no services at all
    create_organisation("org 3")

    # This service isn’t associated to an org, and should not be counted as live
    # because it’s marked as not counted
    create_service(service_name="f3", count_as_live=False)

    # This service isn’t associated to an org, and should not be counted as live
    # because it’s in trial mode
    create_service(service_name="t", restricted=True)
    create_service(service_name="i", restricted=False, active=False)

    assert admin_request.get("status.live_service_and_organisation_counts") == {
        "organisations": 1,
        "services": 4,
    }


# /_status/benchmark


def test_benchmark_returns_404_when_flag_disabled(client):
    response = client.get("/_status/benchmark", headers=WAF_HEADER)
    assert response.status_code == 404


def test_benchmark_returns_404_when_waf_secret_missing(client, notify_db_session):
    with client.application.app_context():
        client.application.config["FF_BENCHMARK_ENDPOINT"] = True
        client.application.config["WAF_SECRET"] = WAF_SECRET
    response = client.get("/_status/benchmark")
    assert response.status_code == 404


def test_benchmark_returns_404_when_waf_secret_wrong(client, notify_db_session):
    with client.application.app_context():
        client.application.config["FF_BENCHMARK_ENDPOINT"] = True
        client.application.config["WAF_SECRET"] = WAF_SECRET
    response = client.get("/_status/benchmark", headers={"waf-secret": "wrong-secret"})
    assert response.status_code == 404


def test_benchmark_returns_200_with_default_delay(client, notify_db_session):
    with client.application.app_context():
        client.application.config["FF_BENCHMARK_ENDPOINT"] = True
        client.application.config["WAF_SECRET"] = WAF_SECRET
    response = client.get("/_status/benchmark", headers=WAF_HEADER)
    assert response.status_code == 200
    body = json.loads(response.get_data(as_text=True))
    assert body["status"] == "ok"
    assert "simulated_delay_ms" in body
    # default target is 100ms, jitter is ±20% → valid range [80, 120]
    assert 80 <= body["simulated_delay_ms"] <= 120


def test_benchmark_respects_delay_ms_param(client, notify_db_session):
    with client.application.app_context():
        client.application.config["FF_BENCHMARK_ENDPOINT"] = True
        client.application.config["WAF_SECRET"] = WAF_SECRET
    response = client.get("/_status/benchmark?delay_ms=0", headers=WAF_HEADER)
    assert response.status_code == 200
    body = json.loads(response.get_data(as_text=True))
    assert body["simulated_delay_ms"] == 0.0


def test_benchmark_returns_400_for_non_integer_delay(client, notify_db_session):
    with client.application.app_context():
        client.application.config["FF_BENCHMARK_ENDPOINT"] = True
        client.application.config["WAF_SECRET"] = WAF_SECRET
    response = client.get("/_status/benchmark?delay_ms=abc", headers=WAF_HEADER)
    assert response.status_code == 400
    body = json.loads(response.get_data(as_text=True))
    assert body["status"] == "error"


def test_benchmark_returns_400_for_negative_delay(client, notify_db_session):
    with client.application.app_context():
        client.application.config["FF_BENCHMARK_ENDPOINT"] = True
        client.application.config["WAF_SECRET"] = WAF_SECRET
    response = client.get("/_status/benchmark?delay_ms=-1", headers=WAF_HEADER)
    assert response.status_code == 400
    body = json.loads(response.get_data(as_text=True))
    assert body["status"] == "error"


def test_benchmark_returns_400_for_delay_exceeding_maximum(client, notify_db_session):
    with client.application.app_context():
        client.application.config["FF_BENCHMARK_ENDPOINT"] = True
        client.application.config["WAF_SECRET"] = WAF_SECRET
    response = client.get("/_status/benchmark?delay_ms=10001", headers=WAF_HEADER)
    assert response.status_code == 400
    body = json.loads(response.get_data(as_text=True))
    assert body["status"] == "error"
