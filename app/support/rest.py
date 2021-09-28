from flask import Blueprint, jsonify
from sqlalchemy.orm.exc import NoResultFound

from app.dao.jobs_dao import dao_get_job_by_id
from app.dao.services_dao import dao_fetch_service_by_id
from app.dao.templates_dao import dao_get_template_by_id
from app.dao.users_dao import get_user_by_id
from app.errors import register_errors

support_blueprint = Blueprint("support", __name__)
register_errors(support_blueprint)


@support_blueprint.route("/<uuid:id>", methods=["GET"])
def get_id_info(id):
    try:
        template = dao_get_template_by_id(id)
    except NoResultFound:
        pass
    else:

        return jsonify(
            {
                "type": "template",
                "id": template.id,
                "name": template.name,
                "service_id": template.service_id,
                "service_name": template.service.name,
            }
        )

    try:
        service = dao_fetch_service_by_id(id)
    except NoResultFound:
        pass
    else:
        return jsonify({"type": "service", "id": service.id, "name": service.name})

    try:
        job = dao_get_job_by_id(id)
    except NoResultFound:
        pass
    else:
        return jsonify(
            {
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
        )

    try:
        user = get_user_by_id(id)
    except NoResultFound:
        pass
    else:
        return jsonify(
            {
                "type": "user",
                "id": user.id,
                "name": user.name,
            }
        )

    return jsonify(data={"type": "no result found"})
