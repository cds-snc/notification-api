import math
import uuid
from functools import cache
from time import time

from flask import current_app, jsonify, request

from app import api_user, authenticated_service
from app.celery.tasks import generate_report
from app.config import QueueNames
from app.dao.reports_dao import create_report
from app.models import ApiKeyPermission, Report, ReportStatus
from app.rate_limiter import RedisSlidingWindowLogRateLimiter
from app.schema_validation import validate
from app.v2.errors import ForbiddenError, ReportRateLimitError
from app.v2.reports import v2_reports_blueprint
from app.v2.reports.report_schemas import post_report_request

REPORT_RATE_LIMIT = 10
REPORT_RATE_WINDOW = 3600  # 1 hour in seconds


@cache
def _get_report_limiter() -> RedisSlidingWindowLogRateLimiter:
    # Module-level singleton; per-service buckets are obtained via `for_scope`.
    return RedisSlidingWindowLogRateLimiter(
        cap_per_window=REPORT_RATE_LIMIT,
        namespace="report-download",
        window_size=REPORT_RATE_WINDOW,
    )


def _check_report_rate_limit(service_id):
    """Enforce a limit of 10 POST /v2/reports requests per hour per service.

    Raises ReportRateLimitError if the limit is exceeded.
    When Redis is unavailable or rate limiting is disabled, the check is skipped.
    """
    if not current_app.config.get("API_RATE_LIMIT_ENABLED") or not current_app.config.get("REDIS_ENABLED"):
        return

    now = time()
    success, seconds_to_wait = _get_report_limiter().for_scope(str(service_id)).acquire_lease()

    if not success:
        reset_at = math.ceil(now + seconds_to_wait)
        retry_after = max(1, seconds_to_wait)
        raise ReportRateLimitError(limit=REPORT_RATE_LIMIT, retry_after=retry_after, reset_at=reset_at)


@v2_reports_blueprint.route("", methods=["POST"])
def post_report():
    if not api_user.has_permission(ApiKeyPermission.MANAGE_REPORTS):
        raise ForbiddenError(message="This API key does not have permission to manage reports.")

    _check_report_rate_limit(authenticated_service.id)

    data = validate(request.get_json(), post_report_request)

    report = Report(
        id=uuid.uuid4(),
        report_type=data["report_type"],
        service_id=authenticated_service.id,
        status=ReportStatus.REQUESTED.value,
        requesting_user_id=None,
        api_key_id=api_user.id,
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
