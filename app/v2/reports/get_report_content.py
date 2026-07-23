import botocore.exceptions
from flask import Response, current_app, jsonify, stream_with_context

from app import api_user, authenticated_service
from app.aws.s3 import stream_report_from_s3
from app.dao.reports_dao import get_report_by_id
from app.models import ApiKeyPermission, ReportStatus
from app.v2.errors import BadRequestError, ForbiddenError
from app.v2.reports import v2_reports_blueprint


@v2_reports_blueprint.route("/<uuid:report_id>/content", methods=["GET"])
def get_report_content(report_id):
    if not api_user.has_permission(ApiKeyPermission.MANAGE_REPORTS):
        raise ForbiddenError(message="This API key does not have permission to manage reports.")

    # get_report_by_id uses .one() — raises NoResultFound (→ 404) when missing
    report = get_report_by_id(str(report_id))

    # Ownership check: return 404 so callers cannot probe for other services' reports
    if str(report.service_id) != str(authenticated_service.id):
        from sqlalchemy.orm.exc import NoResultFound

        raise NoResultFound()

    if report.status != ReportStatus.READY.value:
        raise BadRequestError(
            message=f"Report is not ready for download (status: {report.status})",
            status_code=409,
        )

    try:
        chunks = stream_report_from_s3(report.service_id, report_id)
    except botocore.exceptions.ClientError:
        current_app.logger.error(f"Failed to open S3 object for report {report_id} (service {authenticated_service.id})")
        return (
            jsonify(
                status_code=502,
                errors=[{"error": "S3Error", "message": "Failed to retrieve report content"}],
            ),
            502,
        )

    headers = {
        "Content-Disposition": f'attachment; filename="{report_id}.csv"',
        "Content-Type": "text/csv",
    }
    return Response(stream_with_context(chunks), headers=headers, status=200)
