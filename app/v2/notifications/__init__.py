from flask import Blueprint

from app.v2.errors import register_errors
from app.v2.openapi.api import configure_api
from app.v2.openapi.models import create_models

# Create blueprint
v2_notification_blueprint = Blueprint("v2_notifications", __name__, url_prefix="/v2/notifications")

# Register error handlers
register_errors(v2_notification_blueprint)

# Configure API with OpenAPI specification
api = configure_api(v2_notification_blueprint)

# Create models
models = create_models(api)

# Create namespace
notifications_namespace = api.namespace("notifications", description="Notification operations")
