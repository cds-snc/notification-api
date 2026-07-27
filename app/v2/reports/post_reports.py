import math
import uuid
from time import time

from flask import current_app, jsonify, request

from app import api_user, authenticated_service, redis_store
from app.celery.tasks import generate_report
from app.config import QueueNames
from app.dao.reports_dao import create_report
from app.models import ApiKeyPermission, Report, ReportStatus
from app.schema_validation import validate
from app.v2.errors import ForbiddenError, ReportRateLimitError
from app.v2.reports import v2_reports_blueprint
from app.v2.reports.report_schemas import post_report_request

REPORT_RATE_LIMIT = 10
REPORT_RATE_WINDOW = 3600  # 1 hour in seconds


def _check_report_rate_limit(service_id):
    """Enforce a limit of 10 POST /v2/reports requests per hour per service.

    Raises ReportRateLimitError if the limit is exceeded.
    When Redis is unavailable or rate limiting is disabled, the check is skipped.
    """
    if not current_app.config.get("API_RATE_LIMIT_ENABLED") or not current_app.config.get("REDIS_ENABLED"):
        return

    cache_key = f"report-rate-limit:{service_id}"
    now = time()
    window_start = now - REPORT_RATE_WINDOW

    pipe = redis_store.redis_store.pipeline()
    pipe.zremrangebyscore(cache_key, "-inf", window_start)
    pipe.zcard(cache_key)
    results = pipe.execute()

    count = results[1]

    if count >= REPORT_RATE_LIMIT:
        oldest = redis_store.redis_store.zrange(cache_key, 0, 0, withscores=True)
        if oldest:
            reset_at = math.ceil(oldest[0][1] + REPORT_RATE_WINDOW)
        else:
            reset_at = math.ceil(now + REPORT_RATE_WINDOW)
        retry_after = max(1, reset_at - math.ceil(now))
        raise ReportRateLimitError(limit=REPORT_RATE_LIMIT, retry_after=retry_after, reset_at=reset_at)

    # Record this request in the sliding window
    pipe2 = redis_store.redis_store.pipeline()
    pipe2.zadd(cache_key, {now: now})
    pipe2.expire(cache_key, REPORT_RATE_WINDOW + 60)
    pipe2.execute()


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
