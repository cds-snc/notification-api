import datetime
import uuid

import pytest
from freezegun import freeze_time

from app.dao.reports_dao import create_report, get_reports_for_service
from app.models import Report, ReportStatus, ReportType


def test_create_report(sample_service, notify_db_session):
    report_id = uuid.uuid4()
    report = Report(
        id=report_id,
        report_type=ReportType.SMS.value,
        service_id=sample_service.id,
        status=ReportStatus.REQUESTED.value,
    )

    # Create the report
    created_report = create_report(report)

    # Check the report was created
    assert created_report.id == report_id
    assert created_report.report_type == ReportType.SMS.value
    assert created_report.service_id == sample_service.id
    assert created_report.status == ReportStatus.REQUESTED.value


@pytest.fixture
@freeze_time("2023-01-15 12:00:00")
def sample_reports(sample_service):
    """Create a set of sample reports for testing"""
    reports = []
    # Create reports with different dates
    for i in range(5):
        days_ago = 5 - i  # 5, 4, 3, 2, 1 days ago
        report_date = datetime.datetime.utcnow() - datetime.timedelta(days=days_ago)
        reports.append(
            Report(
                id=uuid.uuid4(),
                service_id=sample_service.id,
                report_type=ReportType.SMS.value,
                requested_at=report_date,
                status=ReportStatus.REQUESTED.value,
                url=None,
                job_id=None,
            )
        )

    # Also add an older report (outside default limit)
    old_report_date = datetime.datetime.utcnow() - datetime.timedelta(days=35)
    reports.append(
        Report(
            id=uuid.uuid4(),
            service_id=sample_service.id,
            report_type=ReportType.EMAIL.value,
            requested_at=old_report_date,
            status=ReportStatus.READY.value,
            url="https://test-bucket.s3.amazonaws.com/test-report.csv",
            job_id=None,
        )
    )

    return reports


@freeze_time("2023-01-15 12:00:00")
def test_get_reports_for_service_with_limit(sample_service, sample_reports, notify_db_session):
    """Test getting reports with a day limit applies filter correctly"""
    # Add the sample reports to the database
    for report in sample_reports:
        create_report(report)

    # Call function with 7 day limit
    result = get_reports_for_service(sample_service.id, limit_days=7)

    # Get expected reports (reports within the 7-day limit)
    expected_reports = [r for r in sample_reports if (datetime.datetime.utcnow() - r.requested_at).days <= 7]
    expected_reports.sort(key=lambda x: x.requested_at, reverse=True)  # Sort by requested_at desc

    assert len(result) == 5  # Should have 5 reports within the 7-day limit
    assert len(result) == len(expected_reports)

    # Verify the oldest report (35 days old) is not included
    oldest_report = [r for r in sample_reports if (datetime.datetime.utcnow() - r.requested_at).days > 30][0]
    assert oldest_report.id not in [r.id for r in result]


def test_get_reports_for_service_empty_result(sample_service, mocker):
    """Test when no reports exist for a service"""
    result = get_reports_for_service(sample_service.id, limit_days=30)
    assert result == []


@freeze_time("2023-01-15 12:00:00")
def test_get_reports_for_service_sorting(sample_service, sample_reports, notify_db_session):
    """Test that reports are sorted by requested_at in descending order"""
    # Add the first 3 reports from sample_reports to the database
    # These will be 5, 4, and 3 days ago
    test_reports = sample_reports[:3]

    for report in test_reports:
        create_report(report)

    # Expected order based on dates: 3 days ago (index 2), 4 days ago (index 1), 5 days ago (index 0)
    expected_order = [test_reports[2], test_reports[1], test_reports[0]]

    # Call function
    result = get_reports_for_service(sample_service.id, limit_days=30)

    # Assertions
    assert len(result) == 3

    # Check that the reports are sorted properly (newest first)
    assert result[0].requested_at > result[1].requested_at > result[2].requested_at

    # Check that the IDs match the expected order
    assert result[0].id == expected_order[0].id
    assert result[1].id == expected_order[1].id
    assert result[2].id == expected_order[2].id
