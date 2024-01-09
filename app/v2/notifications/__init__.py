from flask import Blueprint
from app.v2.errors import register_errors


v2_notification_blueprint = Blueprint('v2_notifications', __name__, url_prefix='/v2/notifications')
from .rest_push import send_push_notification  # noqa

register_errors(v2_notification_blueprint)
