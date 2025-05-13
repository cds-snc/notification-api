"""
This module provides base classes and utilities for implementing RESTful endpoints
using Flask-RESTx Resource classes.
"""

from flask_restx import Resource


class OpenAPIResource(Resource):
    """
    Base class for API resources that implements the OpenAPI specification.

    This class extends the Flask-RESTx Resource class to provide common functionality
    for all API resources in the Notification API.
    """

    def __init__(self, api=None, *args, **kwargs):
        super().__init__(api, *args, **kwargs)


def register_resources(blueprint, namespace, resources):
    """
    Register API resources with both the blueprint and namespace.

    This function handles the registration of Resource classes with both the Flask
    blueprint and the Flask-RESTx namespace.

    Args:
        blueprint: The Flask blueprint to register the resources with
        namespace: The Flask-RESTx namespace to register the resources with
        resources: A dictionary mapping URL patterns to Resource classes
    """
    for url, resource_class in resources.items():
        # Register with Flask blueprint
        view_func = resource_class.as_view(resource_class.__name__)
        blueprint.add_url_rule(url, view_func=view_func, methods=resource_class.methods)

        # Register with Flask-RESTx namespace
        namespace.add_resource(resource_class, url)

    return blueprint
