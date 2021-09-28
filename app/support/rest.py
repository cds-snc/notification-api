from flask import Blueprint, jsonify
from sqlalchemy.orm.exc import NoResultFound

from app.dao.jobs_dao import dao_get_job_by_id
from app.dao.notifications_dao import get_notification_by_id, get_notification_history_by_id
from app.dao.services_dao import dao_fetch_service_by_id
from app.dao.templates_dao import dao_get_template_by_id
from app.dao.users_dao import get_user_by_id
from app.errors import register_errors
from flask import current_app

support_blueprint = Blueprint("support", __name__)
register_errors(support_blueprint)


def notification_query(id):
    try:
        notification = get_notification_by_id(id)
        if notification:
            return {
                "type": "notification",
                "id": notification.id,
                "notification_type": notification.notification_type,
                "status": notification.status,
                "created_at": notification.created_at,
                "sent_at": notification.sent_at,
                "to": notification.to,
                "service_id": notification.service_id,
                "service_name": notification.service.name,
                "job_id": notification.job_id,
                "job_row_number": notification.job_row_number,
                "api_key_id": notification.api_key_id,
            }
    except NoResultFound:
        pass


def notification_history_query(id):
    try:
        notification = get_notification_history_by_id(id)
        if notification:
            return {
                "type": "notification_history",
                "id": notification.id,
                "notification_type": notification.notification_type,
                "status": notification.status,
                "created_at": notification.created_at,
                "sent_at": notification.sent_at,
                "to": "expired",
                "service_id": notification.service_id,
                "service_name": notification.service.name,
                "job_id": notification.job_id,
                "job_row_number": notification.job_row_number,
                "api_key_id": notification.api_key_id,
            }
    except NoResultFound:
        pass


def template_query(id):
    try:
        template = dao_get_template_by_id(id)
        if template:

            return {
                "type": "template",
                "id": template.id,
                "name": template.name,
                "service_id": template.service_id,
                "service_name": template.service.name,
            }
    except NoResultFound:
        pass


def service_query(id):
    try:
        service = dao_fetch_service_by_id(id)
        if service:
            return {"type": "service", "id": service.id, "name": service.name}
    except NoResultFound:
        pass


def job_query(id):
    try:
        job = dao_get_job_by_id(id)
        return {
            "type": "job",
            "id": job.id,
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
        }
    except NoResultFound:
        pass


def user_query(id):
    try:
        user = get_user_by_id(id)
        if user:
            return {
                "type": "user",
                "id": user.id,
                "name": user.name,
            }

    except NoResultFound:
        pass


@support_blueprint.route("/<uuid:id>", methods=["GET"])
def get_id_info(id):

    for query_func in [user_query, service_query, template_query, job_query, notification_query, notification_history_query]:
        results = query_func(id)
        if results:
            return jsonify(results)

    return jsonify(data={"type": "no result found"})
