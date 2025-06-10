import os

from flask import Blueprint, current_app, send_file

v2_api_spec_blueprint = Blueprint("v2_api_spec", __name__, url_prefix="/v2")


@v2_api_spec_blueprint.route("openapi-en", methods=["GET"])
def get_v2_api_spec_en():
    """
    Returns the English OpenAPI specification for the v2 Notifications API.
    """
    spec_path = os.path.join(current_app.root_path, "openapi/v2-notifications-api-en.yaml")
    spec_path = os.path.abspath(spec_path)

    return send_file(spec_path, mimetype="application/yaml", as_attachment=False, download_name="v2-notifications-api.yaml")


@v2_api_spec_blueprint.route("/openapi-fr", methods=["GET"])
def get_v2_api_spec_fr():
    """
    Returns the French OpenAPI specification for the v2 Notifications API.
    """
    spec_path = os.path.join(current_app.root_path, "openapi/v2-notifications-api-fr.yaml")
    spec_path = os.path.abspath(spec_path)

    return send_file(spec_path, mimetype="application/yaml", as_attachment=False, download_name="v2-notifications-api.yaml")
