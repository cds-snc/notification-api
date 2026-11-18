import uuid

from flask import current_app, jsonify, request, url_for

from app import authenticated_service
from app.dao.jobs_dao import (
    dao_get_bulk_jobs_for_service,
    dao_get_job_by_service_id_and_job_id,
    dao_get_job_statistics_for_jobs,
)
from app.errors import InvalidRequest
from app.schema_validation import validate
from app.schemas import job_schema
from app.v2.errors import JobNotFoundError
from app.v2.notifications import v2_notification_blueprint
from app.v2.notifications.notification_schemas import (
    get_bulk_job_request,
    get_bulk_jobs_request,
)


@v2_notification_blueprint.route("/bulk/<job_id>", methods=["GET"])
def get_bulk_job(job_id):
    validate({"job_id": job_id}, get_bulk_job_request)
    job = dao_get_job_by_service_id_and_job_id(authenticated_service.id, job_id)

    if job is None:
        raise JobNotFoundError()

    data = _serialize_jobs_with_statistics([job])[0]
    return jsonify(data=data), 200


@v2_notification_blueprint.route("/bulk", methods=["GET"])
def get_bulk_jobs():
    data = validate(request.args.to_dict(), get_bulk_jobs_request)
    if data.get("older_than") and dao_get_job_by_service_id_and_job_id(authenticated_service.id, data["older_than"]) is None:
        raise InvalidRequest({"older_than": ["Job does not exist for this service"]}, status_code=400)

    paginated_jobs = dao_get_bulk_jobs_for_service(
        authenticated_service.id,
        older_than=data.get("older_than"),
        page_size=current_app.config.get("API_PAGE_SIZE"),
    )
    jobs = _serialize_jobs_with_statistics(paginated_jobs.items)

    links = {
        "current": url_for("v2_notifications.get_bulk_jobs", _external=True, **data),
    }
    if paginated_jobs.items:
        links["next"] = url_for(
            "v2_notifications.get_bulk_jobs",
            _external=True,
            older_than=paginated_jobs.items[-1].id,
        )

    return jsonify(bulk_jobs=jobs, links=links), 200


def _serialize_jobs_with_statistics(jobs):
    data = job_schema.dump(jobs, many=True)
    if not jobs:
        return data

    statistics_by_job = dao_get_job_statistics_for_jobs(jobs)

    for job_data in data:
        job_data["statistics"] = statistics_by_job.get(uuid.UUID(job_data["id"]), [])

    return data
