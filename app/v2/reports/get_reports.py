from flask import current_app, jsonify, request, url_for

from app import api_user, authenticated_service
from app.dao.reports_dao import get_paginated_reports_for_service
from app.models import ApiKeyPermission
from app.v2.errors import ForbiddenError
from app.v2.reports import v2_reports_blueprint


@v2_reports_blueprint.route("", methods=["GET"])
def get_reports():
    if not api_user.has_permission(ApiKeyPermission.MANAGE_REPORTS):
        raise ForbiddenError(message="This API key does not have permission to manage reports.")

    older_than = request.args.get("older_than")

    paginated_reports = get_paginated_reports_for_service(
        service_id=authenticated_service.id,
        older_than=older_than,
        page_size=current_app.config.get("API_PAGE_SIZE"),
    )

    return (
        jsonify(
            reports=[report.serialize() for report in paginated_reports],
            links=_build_links(paginated_reports, older_than),
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
