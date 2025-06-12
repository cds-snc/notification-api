from app.v2.blueprints import PaginationBlueprint
from app.v2.errors import register_v2_errors

v2_notification_blueprint = PaginationBlueprint("v2_notifications", __name__, url_prefix="/v2/notifications", description="")
register_v2_errors(v2_notification_blueprint)
