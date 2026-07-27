from flask import Blueprint, jsonify

from app.v2.errors import ReportRateLimitError, register_errors

v2_reports_blueprint = Blueprint("v2_reports", __name__, url_prefix="/v2/reports")

register_errors(v2_reports_blueprint)


@v2_reports_blueprint.errorhandler(ReportRateLimitError)
def report_rate_limit_error(error):
    response = jsonify(error.to_dict_v2())
    response.status_code = 429
    response.headers["Retry-After"] = str(error.retry_after)
    response.headers["X-RateLimit-Limit"] = str(error.limit)
    response.headers["X-RateLimit-Remaining"] = "0"
    response.headers["X-RateLimit-Reset"] = str(error.reset_at)
    return response
