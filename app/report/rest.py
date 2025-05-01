import uuid

from flask import Blueprint, current_app, jsonify, request
from marshmallow import ValidationError

from app.celery.tasks import generate_report
from app.config import QueueNames
from app.dao.reports_dao import create_report, get_reports_for_service
from app.dao.services_dao import dao_fetch_service_by_id
from app.errors import InvalidRequest, register_errors
from app.models import Report, ReportStatus, ReportType
from app.schema_validation import validate
from app.schemas import report_schema

report_blueprint = Blueprint("report", __name__, url_prefix="/service/<uuid:service_id>/report")
register_errors(report_blueprint)


@report_blueprint.route("", methods=["POST"])
def create_service_report(service_id):
    "Creates a new report for a service"

    data = request.get_json()

    # Validate basic required fields
    validate(data, {"report_type": {"type": "string", "required": True}})

    # Validate report type is one of the allowed types
    report_type = data.get("report_type")
    if report_type not in [rt.value for rt in ReportType]:
        return jsonify(result="error", message=f"Invalid report type: {report_type}"), 400

    # Check service exists
    dao_fetch_service_by_id(service_id)

    try:
        report_data = {
            "id": str(uuid.uuid4()),
            "report_type": report_type,
            "service_id": str(service_id),
            "status": ReportStatus.REQUESTED.value,
            "requesting_user_id": data.get("requesting_user_id"),
            "language": data.get("language"),
            "notification_statuses": data.get("notification_statuses"),
            "job_id": data.get("job_id"),
        }

        # Validate against the schema
        report_schema.load(report_data)

        # Create the report object
        report = Report(
            id=report_data["id"],
            report_type=report_data["report_type"],
            service_id=report_data["service_id"],
            status=report_data["status"],
            requesting_user_id=report_data["requesting_user_id"],
            language=report_data["language"],
            job_id=report_data["job_id"],
        )

        # Save the report to the database
        created_report = create_report(report)

        current_app.logger.info(f"Report {created_report.id} created for service {service_id}")
        notification_statuses = report_data["notification_statuses"] if report_data["notification_statuses"] else []
        # start the report generation process in celery
        current_app.logger.info(f"Calling generate_report for Report ID {report.id}")
        generate_report.apply_async([report.id, notification_statuses], queue=QueueNames.GENERATE_REPORTS)

        return jsonify(data=report_schema.dump(created_report)), 201

    except ValidationError as err:
        errors = err.messages
        raise InvalidRequest(errors, status_code=400)


@report_blueprint.route("", methods=["GET"])
def get_service_reports(service_id):
    """Get reports for a service with optional limit_days parameter"""

    # Get optional days parameter, default to 7 if not provided
    limit_days = request.args.get("limit_days", type=int, default=7)

    # Check service exists
    dao_fetch_service_by_id(service_id)

    reports = get_reports_for_service(service_id, limit_days)

    # Serialize all reports using the schema
    return jsonify(data=report_schema.dump(reports, many=True)), 200


@report_blueprint.route("/totals", methods=["GET"])
def get_report_totals(service_id):
    report_totals = get_report_totals(service_id)
    return jsonify(report_totals), 200
