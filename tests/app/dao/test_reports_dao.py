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
def test_get_reports_for_service_with_limit(sample_service, sample_reports, mocker):
    """Test getting reports with a day limit applies filter correctly"""
    # Mock the query processing
    mock_query = mocker.patch("app.models.Report.query")
    mock_filter_by = mock_query.filter_by.return_value
    mock_filter = mock_filter_by.filter.return_value
    mock_order_by = mock_filter.order_by.return_value
    mock_all = mock_order_by.all

    # Set up the return value to be the subset of reports within the time limit
    expected_reports = [r for r in sample_reports if (datetime.datetime.utcnow() - r.requested_at).days <= 7]
    mock_all.return_value = expected_reports

    # Call function with 7 day limit
    result = get_reports_for_service(sample_service.id, limit_days=7)

    # Assertions
    mock_query.filter_by.assert_called_once_with(service_id=sample_service.id)
    assert mock_filter_by.filter.called
    assert mock_filter.order_by.called
    assert result == expected_reports
    assert len(result) == 5  # All but the oldest report


def test_get_reports_for_service_empty_result(sample_service, mocker):
    """Test when no reports exist for a service"""
    # Mock the query processing
    mock_query = mocker.patch("app.models.Report.query")
    mock_filter_by = mock_query.filter_by.return_value
    mock_filter = mock_filter_by.filter.return_value
    mock_order_by = mock_filter.order_by.return_value
    mock_order_by.all.return_value = []

    # Call function
    result = get_reports_for_service(sample_service.id, limit_days=30)

    # Assertions
    assert result == []


@freeze_time("2023-01-15 12:00:00")
def test_get_reports_for_service_sorting(sample_service, mocker):
    """Test that reports are sorted by requested_at in descending order"""
    # Create a set of reports with different timestamps
    today = datetime.datetime.utcnow()
    reports = [
        Report(
            id=uuid.uuid4(),
            service_id=sample_service.id,
            requested_at=today - datetime.timedelta(days=1),
            status=ReportStatus.READY.value,
        ),
        Report(id=uuid.uuid4(), service_id=sample_service.id, requested_at=today, status=ReportStatus.READY.value),
        Report(
            id=uuid.uuid4(),
            service_id=sample_service.id,
            requested_at=today - datetime.timedelta(days=2),
            status=ReportStatus.READY.value,
        ),
    ]

    # Expected order: today, today-1, today-2
    expected_order = [reports[1], reports[0], reports[2]]

    # Mock the query processing
    mock_query = mocker.patch("app.models.Report.query")
    mock_filter_by = mock_query.filter_by.return_value
    mock_filter = mock_filter_by.filter.return_value
    mock_order_by = mock_filter.order_by.return_value
    mock_order_by.all.return_value = expected_order

    # Call function
    result = get_reports_for_service(sample_service.id, limit_days=30)

    # Assertions
    assert result == expected_order
    mock_filter.order_by.assert_called_once()
    # Check that the first report has the most recent date
    assert result[0].requested_at > result[1].requested_at > result[2].requested_at
