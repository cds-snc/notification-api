import uuid

from app.dao.reports_dao import create_report
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
