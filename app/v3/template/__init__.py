from flask import Blueprint

from app.v2.errors import register_errors

v3_template_blueprint = Blueprint("v3_template", __name__, url_prefix="/v3/template")

register_errors(v3_template_blueprint)  # noqa — registers routes on the blueprint
