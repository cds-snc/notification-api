import os

from flask import Blueprint, current_app, request, send_file

v2_api_spec_blueprint = Blueprint("v2_api_spec", __name__, url_prefix="/v2/api-spec")


@v2_api_spec_blueprint.route("", methods=["GET"])
def get_v2_api_spec():
    """
    Returns the OpenAPI specification for the v2 Notifications API.
    The specification is available in either English or French, based on the 'lang' query parameter.
    If the 'lang' parameter is not provided, it defaults to English.
    """
    lang = request.args.get("lang", "en")
    if lang not in ["en", "fr"]:
        return {"error": "Language not supported"}, 400

    spec_filename = f"v2-notifications-api-{lang}.yaml"
    spec_path = os.path.join(current_app.root_path, f"openapi/{spec_filename}")
    spec_path = os.path.abspath(spec_path)

    return send_file(spec_path, mimetype="application/yaml", as_attachment=False, download_name="v2-notifications-api.yaml")
