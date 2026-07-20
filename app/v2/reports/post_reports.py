import uuid

from flask import current_app, jsonify, request

from app import authenticated_service
from app.celery.tasks import generate_report
from app.config import QueueNames
from app.dao.reports_dao import create_report
from app.models import Report, ReportStatus
from app.schema_validation import validate
from app.v2.reports import v2_reports_blueprint
from app.v2.reports.report_schemas import post_report_request


@v2_reports_blueprint.route("", methods=["POST"])
def post_report():
    data = validate(request.get_json(), post_report_request)

    report = Report(
        id=uuid.uuid4(),
        report_type=data["report_type"],
        service_id=authenticated_service.id,
        status=ReportStatus.REQUESTED.value,
        requesting_user_id=None,
        language=data["language"],
        job_id=data.get("job_id"),
    )
    created_report = create_report(report)

    current_app.logger.info(f"Report {created_report.id} requested via API for service {authenticated_service.id}")
    generate_report.apply_async([str(created_report.id), []], queue=QueueNames.GENERATE_REPORTS)
    response = jsonify(report_id=str(created_report.id), status=created_report.status)
    response.status_code = 202
    response.headers["Location"] = f"/v2/reports/{created_report.id}"
    return response
