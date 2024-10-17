from uuid import UUID

from flask import Blueprint, Response, jsonify, request
from sqlalchemy.orm.exc import NoResultFound

from app.dao.jobs_dao import dao_get_job_by_id
from app.dao.notifications_dao import get_notification_by_id
from app.dao.services_dao import dao_fetch_service_by_id
from app.dao.templates_dao import dao_get_template_by_id
from app.dao.users_dao import get_user_by_id
from app.errors import register_errors

support_blueprint = Blueprint("support", __name__)
register_errors(support_blueprint)


def notification_query(id: str) -> dict | None:
    try:
        notification = get_notification_by_id(id)
        if notification:
            return {
                "id": notification.id,
                "type": "notification",
                "notification_type": notification.notification_type,
                "status": notification.status,
                "created_at": notification.created_at,
                "sent_at": notification.sent_at,
                "to": notification.to,
                "service_id": notification.service_id,
                "service_name": notification.service.name,
                "template_id": notification.template_id,
                "template_name": notification.template.name,
                "job_id": notification.job_id,
                "job_row_number": notification.job_row_number,
                "api_key_id": notification.api_key_id,
            }
    except NoResultFound:
        return None
    return None


def template_query(id: str) -> dict | None:
    try:
        template = dao_get_template_by_id(id)
        if template:
            return {
                "id": template.id,
                "type": "template",
                "template_name": template.name,
                "service_id": template.service_id,
                "service_name": template.service.name,
            }
    except NoResultFound:
        return None
    return None


def service_query(id: str) -> dict | None:
    try:
        service = dao_fetch_service_by_id(id)
        if service:
            return {"id": service.id, "type": "service", "service_name": service.name}
    except NoResultFound:
        return None
    return None


def job_query(id: str) -> dict | None:
    try:
        job = dao_get_job_by_id(id)
        if job:
            return {
                "id": job.id,
                "type": "job",
                "original_file_name": job.original_file_name,
                "created_at": job.created_at,
                "created_by_id": job.created_by_id,
                "created_by_name": job.created_by.name,
                "processing_started": job.processing_started,
                "processing_finished": job.processing_finished,
                "notification_count": job.notification_count,
                "job_status": job.job_status,
                "service_id": job.service_id,
                "service_name": job.service.name,
                "template_id": job.template_id,
                "template_name": job.template.name,
            }
    except NoResultFound:
        return None
    return None


def user_query(id: str) -> dict | None:
    try:
        user = get_user_by_id(id)
        if user:
            return {
                "id": user.id,
                "type": "user",
                "user_name": user.name,
            }
    except NoResultFound:
        return None
    return None


@support_blueprint.route("/find-ids", methods=["GET"])
def find_ids() -> Response:
    ids = request.args.get("ids")
    if not ids:
        return jsonify({"error": "no ids provided"})

    info = []
    for id in ids.replace(",", " ").split():
        try:
            UUID(id)
        except ValueError:
            info.append({"id": id, "type": "not a uuid"})
            continue
        for query_func in [user_query, service_query, template_query, job_query, notification_query]:
            results = query_func(id)
            if results:
                info.append(results)
                break
        if not results:
            info.append({"id": id, "type": "no result found"})
    return jsonify(info)
