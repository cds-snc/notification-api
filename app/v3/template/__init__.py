from flask import Blueprint

from app.errors import register_errors

v3_template_blueprint = Blueprint("v3_template", __name__, url_prefix="/v3/template")

register_errors(v3_template_blueprint)
