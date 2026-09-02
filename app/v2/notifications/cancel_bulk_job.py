from datetime import datetime

from flask import jsonify

from app import authenticated_service
from app.dao.jobs_dao import dao_get_job_by_service_id_and_job_id, dao_update_job
from app.email_limit_utils import decrement_todays_email_count
from app.models import JOB_STATUS_CANCELLED, JOB_STATUS_SCHEDULED
from app.schema_validation import validate
from app.v2.errors import JobCancellationNotAllowedError, JobNotFoundError
from app.v2.notifications import v2_notification_blueprint
from app.v2.notifications.get_bulk_jobs import _serialize_jobs_with_statistics
from app.v2.notifications.notification_schemas import get_bulk_job_request


@v2_notification_blueprint.route("/bulk/<job_id>", methods=["DELETE"])
def cancel_bulk_job(job_id):
    validate({"job_id": job_id}, get_bulk_job_request)

    job = dao_get_job_by_service_id_and_job_id(authenticated_service.id, job_id)
    if job is None:
        raise JobNotFoundError()

    if job.job_status != JOB_STATUS_SCHEDULED or job.scheduled_for <= datetime.utcnow():
        raise JobCancellationNotAllowedError()

    job.job_status = JOB_STATUS_CANCELLED
    dao_update_job(job)
    decrement_todays_email_count(authenticated_service.id, job.notification_count)

    data = _serialize_jobs_with_statistics([job])[0]
    return jsonify(data=data), 200
