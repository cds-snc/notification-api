from functools import wraps


def document_response(func):
    """
    Decorator to document API responses for OpenAPI.
    This decorator doesn't change the behavior of the function,
    it only adds metadata that can be used by OpenAPI generators.
    """

    @wraps(func)
    def decorated_function(*args, **kwargs):
        return func(*args, **kwargs)

    return decorated_function


def api_route(namespace, name, description, model=None, responses=None):
    """
    Decorator to add an API route to a namespace.
    This decorator helps adding OpenAPI documentation to routes.

    Args:
        namespace: The Flask-RESTx namespace
        name: The name of the API route
        description: The description of the API route
        model: The model to expect in the request body
        responses: Dictionary of response codes and descriptions
    """

    def decorator(func):
        @wraps(func)
        def decorated_function(*args, **kwargs):
            return func(*args, **kwargs)

        decorated_function.__apidoc__ = {
            "name": name,
            "description": description,
        }

        if model:
            decorated_function.__apidoc__["model"] = model

        if responses:
            decorated_function.__apidoc__["responses"] = responses

        return decorated_function

    return decorator
