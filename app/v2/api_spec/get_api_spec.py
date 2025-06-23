import os

import yaml  # type: ignore
from flask import Blueprint, Response, current_app

v2_api_spec_blueprint = Blueprint("v2_api_spec", __name__, url_prefix="/v2")


@v2_api_spec_blueprint.route("/openapi-en", methods=["GET"])
def get_v2_api_spec_en():
    """
    Returns the English OpenAPI specification for the v2 Notifications API.
    """
    spec_path = os.path.join(current_app.root_path, "openapi/v2-notifications-api-en.yaml")
    spec_path = os.path.abspath(spec_path)

    with open(spec_path, "r") as f:
        yaml_data = yaml.safe_load(f)

    yaml_string = yaml.dump(yaml_data, default_flow_style=False)
    response = Response(yaml_string, mimetype="application/yaml")
    return response


@v2_api_spec_blueprint.route("/openapi-fr", methods=["GET"])
def get_v2_api_spec_fr():
    """
    Returns the French OpenAPI specification for the v2 Notifications API.
    """
    spec_path = os.path.join(current_app.root_path, "openapi/v2-notifications-api-fr.yaml")
    spec_path = os.path.abspath(spec_path)

    with open(spec_path, "r") as f:
        yaml_data = f.read()

    response = Response(yaml_data, mimetype="application/yaml")
    return response
