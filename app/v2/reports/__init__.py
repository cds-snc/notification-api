from flask import Blueprint

from app.v2.errors import register_errors

v2_reports_blueprint = Blueprint("v2_reports", __name__, url_prefix="/v2/reports")

register_errors(v2_reports_blueprint)


def reports_api_enabled(environment: str) -> bool:
    """The reports API endpoints are hidden in production environments until launch."""
    return environment not in ("production", "production_ff")
