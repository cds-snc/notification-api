from flask import jsonify

from app import authenticated_service
from app.dao import notifications_dao
from app.schema_validation import validate
from app.v2.errors import BadRequestError
from app.v2.notifications import v2_notification_blueprint
from app.v2.notifications.notification_schemas import notification_by_id


@v2_notification_blueprint.route("/<notification_id>", methods=["DELETE"])
def delete_notification_by_id(notification_id):
    _data = {"notification_id": notification_id}
    validate(_data, notification_by_id)

    notification = notifications_dao.get_notification_by_id(notification_id, authenticated_service.id)

    if notification is None:
        return jsonify(result="error", message="Notification not found in database"), 404

    scheduled_notification = notification.scheduled_notification
    if scheduled_notification is None:
        raise BadRequestError(message="Notification is not scheduled and cannot be deleted")

    if not scheduled_notification.pending:
        raise BadRequestError(message="Notification has already been sent and cannot be deleted")

    notifications_dao.dao_delete_scheduled_notification_by_id(notification_id)

    return jsonify(result="success"), 200
