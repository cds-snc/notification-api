import json
import uuid

from app.dao.reports_dao import create_report
from app.models import Report, ReportStatus, ReportType
from tests import create_authorization_header


def _make_report(
    service_id, report_type=ReportType.EMAIL.value, status=ReportStatus.READY.value, url="https://s3.example.com/report.csv"
):
    return Report(
        id=uuid.uuid4(),
        report_type=report_type,
        service_id=service_id,
        status=status,
        requesting_user_id=None,
        language="en",
        url=url,
    )


def test_get_reports_returns_200(client, sample_service, create_api_key_with_manage_reports_perm):
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    create_report(_make_report(sample_service.id))

    response = client.get(
        path="/v2/reports",
        headers=[auth_header],
    )

    assert response.status_code == 200


def test_get_reports_returns_list_of_reports(client, sample_service, create_api_key_with_manage_reports_perm):
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    report = _make_report(sample_service.id)
    create_report(report)

    response = client.get(
        path="/v2/reports",
        headers=[auth_header],
    )

    data = json.loads(response.get_data(as_text=True))
    assert len(data["reports"]) == 1
    assert data["reports"][0]["id"] == str(report.id)
    assert data["reports"][0]["report_type"] == report.report_type
    assert data["reports"][0]["status"] == report.status


def test_get_reports_does_not_include_url(client, sample_service, create_api_key_with_manage_reports_perm):
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    create_report(_make_report(sample_service.id))

    response = client.get(
        path="/v2/reports",
        headers=[auth_header],
    )

    data = json.loads(response.get_data(as_text=True))
    assert "url" not in data["reports"][0]


def test_get_reports_returns_only_reports_for_service(
    client, sample_service, notify_db_session, create_api_key_with_manage_reports_perm
):
    from tests.app.db import create_service

    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    other_service = create_service(service_name="other service")

    create_report(_make_report(sample_service.id))
    create_report(_make_report(other_service.id))

    response = client.get(
        path="/v2/reports",
        headers=[auth_header],
    )

    data = json.loads(response.get_data(as_text=True))
    assert len(data["reports"]) == 1
    assert data["reports"][0]["service_id"] == str(sample_service.id)


def test_get_reports_returns_links(client, sample_service, create_api_key_with_manage_reports_perm):
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    create_report(_make_report(sample_service.id))

    response = client.get(
        path="/v2/reports",
        headers=[auth_header],
    )

    data = json.loads(response.get_data(as_text=True))
    assert "links" in data
    assert "current" in data["links"]
    assert "next" in data["links"]


def test_get_reports_empty_list_has_no_next_link(client, sample_service, create_api_key_with_manage_reports_perm):
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)

    response = client.get(
        path="/v2/reports",
        headers=[auth_header],
    )

    data = json.loads(response.get_data(as_text=True))
    assert data["reports"] == []
    assert "next" not in data["links"]


def test_get_reports_returns_403_without_manage_reports_permission(client, create_api_key_no_perm):
    auth_header = create_authorization_header(api_key=create_api_key_no_perm)

    response = client.get(
        path="/v2/reports",
        headers=[auth_header],
    )

    assert response.status_code == 403
    data = json.loads(response.get_data(as_text=True))
    assert "manage reports" in data["errors"][0]["message"].lower()


def test_get_reports_requires_authentication(client):
    response = client.get(path="/v2/reports")

    assert response.status_code == 401


def test_get_reports_pagination_with_older_than(
    client, sample_service, notify_db_session, create_api_key_with_manage_reports_perm, mocker
):
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    mocker.patch.dict("app.v2.reports.get_reports.current_app.config", {"API_PAGE_SIZE": 1})

    report1 = _make_report(sample_service.id)
    report2 = _make_report(sample_service.id)
    create_report(report1)
    create_report(report2)

    # Fetch first page
    response = client.get(path="/v2/reports", headers=[auth_header])
    data = json.loads(response.get_data(as_text=True))
    assert len(data["reports"]) == 1
    first_id = data["reports"][0]["id"]

    # Fetch next page using older_than
    response2 = client.get(path=f"/v2/reports?older_than={first_id}", headers=[auth_header])
    data2 = json.loads(response2.get_data(as_text=True))
    assert len(data2["reports"]) == 1
    assert data2["reports"][0]["id"] != first_id


def test_get_reports_returns_400_for_invalid_older_than(client, sample_service, create_api_key_with_manage_reports_perm):
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)

    response = client.get(path="/v2/reports?older_than=not-a-uuid", headers=[auth_header])

    assert response.status_code == 400


# ---- GET /v2/reports/<report_id> tests ----


def test_get_report_by_id_returns_200(client, sample_service, create_api_key_with_manage_reports_perm):
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    report = _make_report(sample_service.id)
    create_report(report)

    response = client.get(path=f"/v2/reports/{report.id}", headers=[auth_header])

    assert response.status_code == 200


def test_get_report_by_id_returns_report_fields(client, sample_service, create_api_key_with_manage_reports_perm):
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    report = _make_report(sample_service.id)
    create_report(report)

    response = client.get(path=f"/v2/reports/{report.id}", headers=[auth_header])

    data = json.loads(response.get_data(as_text=True))
    assert data["id"] == str(report.id)
    assert data["report_type"] == report.report_type
    assert data["status"] == report.status
    assert data["service_id"] == str(sample_service.id)


def test_get_report_by_id_does_not_include_url(client, sample_service, create_api_key_with_manage_reports_perm):
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    report = _make_report(sample_service.id)
    create_report(report)

    response = client.get(path=f"/v2/reports/{report.id}", headers=[auth_header])

    data = json.loads(response.get_data(as_text=True))
    assert "url" not in data


def test_get_report_by_id_returns_404_for_nonexistent_id(client, sample_service, create_api_key_with_manage_reports_perm):
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)

    response = client.get(path=f"/v2/reports/{uuid.uuid4()}", headers=[auth_header])

    assert response.status_code == 404


def test_get_report_by_id_returns_404_for_other_services_report(
    client, sample_service, notify_db_session, create_api_key_with_manage_reports_perm
):
    from tests.app.db import create_service

    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)
    other_service = create_service(service_name="other service")
    other_report = _make_report(other_service.id)
    create_report(other_report)

    response = client.get(path=f"/v2/reports/{other_report.id}", headers=[auth_header])

    assert response.status_code == 404


def test_get_report_by_id_returns_403_without_manage_reports_permission(client, sample_service, create_api_key_no_perm):
    auth_header = create_authorization_header(api_key=create_api_key_no_perm)

    response = client.get(path=f"/v2/reports/{uuid.uuid4()}", headers=[auth_header])

    assert response.status_code == 403
    data = json.loads(response.get_data(as_text=True))
    assert "manage reports" in data["errors"][0]["message"].lower()


def test_get_report_by_id_requires_authentication(client):
    response = client.get(path=f"/v2/reports/{uuid.uuid4()}")

    assert response.status_code == 401


def test_get_report_by_id_returns_400_for_invalid_id(client, sample_service, create_api_key_with_manage_reports_perm):
    auth_header = create_authorization_header(api_key=create_api_key_with_manage_reports_perm)

    response = client.get(path="/v2/reports/not-a-uuid", headers=[auth_header])

    assert response.status_code == 400
