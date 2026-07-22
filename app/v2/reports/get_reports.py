from flask import current_app, jsonify, request, url_for

from app import api_user, authenticated_service
from app.dao.reports_dao import get_paginated_reports_for_service
from app.models import ApiKeyPermission
from app.schema_validation import validate
from app.v2.errors import ForbiddenError
from app.v2.reports import v2_reports_blueprint
from app.v2.reports.report_schemas import get_reports_request


@v2_reports_blueprint.route("", methods=["GET"])
def get_reports():
    if not api_user.has_permission(ApiKeyPermission.MANAGE_REPORTS):
        raise ForbiddenError(message="This API key does not have permission to manage reports.")

    data = validate(request.args.to_dict(), get_reports_request)
    older_than = data.get("older_than")

    paginated_reports = get_paginated_reports_for_service(
        service_id=authenticated_service.id,
        older_than=older_than,
        page_size=current_app.config.get("API_PAGE_SIZE"),
    )

    excluded_fields = {"url"}

    return (
        jsonify(
            reports=[
                {k: v for k, v in report.serialize().items() if k not in excluded_fields} for report in paginated_reports.items
            ],
            links=_build_links(paginated_reports.items, older_than),
        ),
        200,
    )


def _build_links(reports_list, older_than=None):
    _links = {
        "current": url_for(
            "v2_reports.get_reports",
            _external=True,
            **{"older_than": older_than} if older_than else {},
        ),
    }

    if reports_list:
        _links["next"] = url_for(
            "v2_reports.get_reports",
            older_than=reports_list[-1].id,
            _external=True,
        )

    return _links
