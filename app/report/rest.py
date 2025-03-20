import uuid

from flask import Blueprint, current_app, jsonify, request

from app.dao.reports_dao import create_report
from app.dao.services_dao import dao_fetch_service_by_id
from app.errors import register_errors
from app.models import Report, ReportStatus, ReportType
from app.schema_validation import validate

report_blueprint = Blueprint("report", __name__, url_prefix="/service/<uuid:service_id>/report")
register_errors(report_blueprint)


@report_blueprint.route("", methods=["POST"])
def create_service_report(service_id):
    """
    Creates a new report for a service
    ---
    tags:
      - Report
    parameters:
      - name: service_id
        in: path
        type: string
        required: true
        description: The ID of the service
    requestBody:
      content:
        application/json:
          schema:
            type: object
            properties:
              report_type:
                type: string
                enum: [sms, email, job]
                description: Type of report to generate
              requesting_user_id:
                type: string
                format: uuid
                description: ID of the user requesting the report
            required:
              - report_type
    responses:
      201:
        description: Report request created
      400:
        description: Invalid request
      403:
        description: Unauthorized
    """
    data = request.get_json()

    validate(data, {"report_type": {"type": "string", "required": True}})

    # Validate report type is one of the allowed types
    report_type = data.get("report_type")
    if report_type not in [rt.value for rt in ReportType]:
        return jsonify(result="error", message=f"Invalid report type: {report_type}"), 400

    # Check service exists
    dao_fetch_service_by_id(service_id)

    # Create the report object
    report = Report(
        id=uuid.uuid4(),
        report_type=report_type,
        service_id=service_id,
        status=ReportStatus.REQUESTED.value,
        requesting_user_id=data.get("requesting_user_id"),
    )

    # Save the report to the database
    created_report = create_report(report)

    current_app.logger.info(f"Report {created_report.id} created for service {service_id}")

    return jsonify(data=created_report.serialize()), 201
