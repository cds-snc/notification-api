from flask import Blueprint

from app.v2.errors import register_errors

v2_manage_template_blueprint = Blueprint("v2_manage_template", __name__, url_prefix="/v2/manage-template")

register_errors(v2_manage_template_blueprint)
