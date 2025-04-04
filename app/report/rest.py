import uuid

from flask import Blueprint, current_app, jsonify, request
from marshmallow import ValidationError

from app.dao.reports_dao import create_report, get_reports_for_service
from app.dao.services_dao import dao_fetch_service_by_id
from app.errors import InvalidRequest, register_errors
from app.models import Report, ReportStatus
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

    # Check service exists
    dao_fetch_service_by_id(service_id)

    try:
        # Validate the report data against the schema
        report_data = {
            "id": str(uuid.uuid4()),
            "report_type": data.get("report_type"),
            "service_id": str(service_id),
            "status": ReportStatus.REQUESTED.value,
            "requesting_user_id": data.get("requesting_user_id"),
            "language": data.get("language"),
        }

        # Validate against the schema
        report_schema.load(report_data)

        # Create the report object
        report = Report(**report_data)

        # Save the report to the database
        created_report = create_report(report)

        current_app.logger.info(f"Report {created_report.id} created for service {service_id}")

        return jsonify(data=report_schema.dump(created_report)), 201

    except ValidationError as err:
        errors = err.messages
        raise InvalidRequest(errors, status_code=400)


@report_blueprint.route("", methods=["GET"])
def get_service_reports(service_id):
    """Get reports for a service with optional limit_days parameter"""

    # Get optional days parameter, default to 30 if not provided
    limit_days = request.args.get("limit_days", type=int, default=30)

    # Check service exists
    dao_fetch_service_by_id(service_id)

    reports = get_reports_for_service(service_id, limit_days)

    # Serialize all reports using the schema
    return jsonify(data=report_schema.dump(reports, many=True)), 200
