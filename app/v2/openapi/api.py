from flask import url_for
from flask_restx import Api


class CustomAPI(Api):
    @property
    def specs_url(self):
        """
        Override the default specs_url to use the url_for function
        """
        return url_for(self.endpoint("specs"))


def configure_api(blueprint):
    """
    Configure the OpenAPI specification for a blueprint.

    Args:
        blueprint: The Flask blueprint to configure

    Returns:
        The configured API object
    """
    authorizations = {"apikey": {"type": "apiKey", "in": "header", "name": "Authorization"}}

    api = CustomAPI(
        blueprint,
        version="2.0",
        title="GOV.UK Notify API",
        description="The GOV.UK Notify API lets you send emails, text messages and letters.",
        doc="/docs",
        authorizations=authorizations,
        security="apikey",
    )

    return api
