import os

import pytest

from tests import create_authorization_header

# Map of environment to allowed origins (should match app/__init__.py)
ALLOWED_ORIGINS = {
    "development": {"http://localhost:8081"},
    "dev": {"https://documentation.dev.notification.cdssandbox.xyz"},
    "staging": {"https://documentation.staging.notification.cdssandbox.xyz", "https://cds-snc.github.io"},
    "production": {"https://documentation.notification.canada.ca"},
    "test": {"http://localhost:8081"},
}


def get_env():
    return os.environ.get("NOTIFY_ENVIRONMENT", "development")


def get_invalid_origin():
    return "https://malicious-site.com"


# List of all environments and one allowed origin for each
ENV_ORIGINS = [
    ("development", "http://localhost:8081"),
    ("dev", "https://documentation.dev.notification.cdssandbox.xyz"),
    ("staging", "https://documentation.staging.notification.cdssandbox.xyz"),
    ("staging", "https://cds-snc.github.io"),  # Test both allowed origins for staging
    ("production", "https://documentation.notification.canada.ca"),
    ("test", "http://localhost:8081"),
]


@pytest.mark.parametrize("env, origin", ENV_ORIGINS)
def test_cors_headers_set_on_api_request(notify_api, env, origin):
    # Save the original environment and config
    original_env = os.environ.get("NOTIFY_ENVIRONMENT")
    original_config = notify_api.config.get("NOTIFY_ENVIRONMENT")

    try:
        # Set environment for test
        os.environ["NOTIFY_ENVIRONMENT"] = env
        notify_api.config["NOTIFY_ENVIRONMENT"] = env

        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                allow_headers = "Content-Type,Authorization"
                allow_methods = "GET,PUT,POST,DELETE"
                response = client.get(
                    path="/v2/notifications",
                    headers=[("Origin", origin)],
                )

                assert response.status_code == 401
                assert response.headers["Access-Control-Allow-Origin"] == origin
                assert response.headers["Access-Control-Allow-Headers"] == allow_headers
                assert response.headers["Access-Control-Allow-Methods"] == allow_methods
    finally:
        # Restore original environment and config
        if original_env is None:
            if "NOTIFY_ENVIRONMENT" in os.environ:
                del os.environ["NOTIFY_ENVIRONMENT"]
        else:
            os.environ["NOTIFY_ENVIRONMENT"] = original_env

        notify_api.config["NOTIFY_ENVIRONMENT"] = original_config


# Original test replaced with parameterized version below


@pytest.mark.parametrize("env, origin", ENV_ORIGINS)
def test_cors_headers_work_with_options_method(notify_api, env, origin):
    # Save the original environment and config
    original_env = os.environ.get("NOTIFY_ENVIRONMENT")
    original_config = notify_api.config.get("NOTIFY_ENVIRONMENT")

    try:
        # Set environment for test
        os.environ["NOTIFY_ENVIRONMENT"] = env
        notify_api.config["NOTIFY_ENVIRONMENT"] = env

        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                allow_headers = "Content-Type,Authorization"
                allow_methods = "GET,PUT,POST,DELETE"
                response = client.options(
                    path="/v2/notifications",
                    headers=[("Origin", origin)],
                )

                assert response.status_code == 200
                assert response.headers["Access-Control-Allow-Origin"] == origin
                assert response.headers["Access-Control-Allow-Headers"] == allow_headers
                assert response.headers["Access-Control-Allow-Methods"] == allow_methods
    finally:
        # Restore original environment and config
        if original_env is None:
            if "NOTIFY_ENVIRONMENT" in os.environ:
                del os.environ["NOTIFY_ENVIRONMENT"]
        else:
            os.environ["NOTIFY_ENVIRONMENT"] = original_env

        notify_api.config["NOTIFY_ENVIRONMENT"] = original_config


@pytest.mark.parametrize("env, origin", ENV_ORIGINS)
def test_cors_headers_with_auth_protected_route(notify_api, sample_service, env, origin):
    # Save the original environment and config
    original_env = os.environ.get("NOTIFY_ENVIRONMENT")
    original_config = notify_api.config.get("NOTIFY_ENVIRONMENT")

    try:
        # Set environment for test
        os.environ["NOTIFY_ENVIRONMENT"] = env
        notify_api.config["NOTIFY_ENVIRONMENT"] = env

        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                allow_headers = "Content-Type,Authorization"
                allow_methods = "GET,PUT,POST,DELETE"
                auth_header = create_authorization_header()
                response = client.get(
                    path=f"/service/{sample_service.id}",
                    headers=[("Origin", origin), auth_header],
                )

                assert response.status_code == 200
                assert response.headers["Access-Control-Allow-Origin"] == origin
                assert response.headers["Access-Control-Allow-Headers"] == allow_headers
                assert response.headers["Access-Control-Allow-Methods"] == allow_methods
    finally:
        # Restore original environment and config
        if original_env is None:
            if "NOTIFY_ENVIRONMENT" in os.environ:
                del os.environ["NOTIFY_ENVIRONMENT"]
        else:
            os.environ["NOTIFY_ENVIRONMENT"] = original_env

        notify_api.config["NOTIFY_ENVIRONMENT"] = original_config


@pytest.mark.parametrize("env, origin", ENV_ORIGINS)
def test_cors_options_with_auth_protected_route(notify_api, sample_service, env, origin):
    # Save the original environment and config
    original_env = os.environ.get("NOTIFY_ENVIRONMENT")
    original_config = notify_api.config.get("NOTIFY_ENVIRONMENT")

    try:
        # Set environment for test
        os.environ["NOTIFY_ENVIRONMENT"] = env
        notify_api.config["NOTIFY_ENVIRONMENT"] = env

        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                allow_headers = "Content-Type,Authorization"
                allow_methods = "GET,PUT,POST,DELETE"
                response = client.options(
                    path=f"/service/{sample_service.id}",
                    headers=[("Origin", origin)],
                )

                assert response.status_code == 401
                assert response.headers["Access-Control-Allow-Origin"] == origin
                assert response.headers["Access-Control-Allow-Headers"] == allow_headers
                assert response.headers["Access-Control-Allow-Methods"] == allow_methods
    finally:
        # Restore original environment and config
        if original_env is None:
            if "NOTIFY_ENVIRONMENT" in os.environ:
                del os.environ["NOTIFY_ENVIRONMENT"]
        else:
            os.environ["NOTIFY_ENVIRONMENT"] = original_env

        notify_api.config["NOTIFY_ENVIRONMENT"] = original_config


def test_all_allowed_origins_are_covered_in_tests():
    """
    This test ensures that all environments and origins defined in ALLOWED_ORIGINS
    are properly covered in our parameterized tests.
    """
    # Extract all environment-origin pairs from ENV_ORIGINS
    tested_pairs = set((env, origin) for env, origin in ENV_ORIGINS)

    # Create a set of all environment-origin pairs from ALLOWED_ORIGINS
    expected_pairs = set()
    for env, origins in ALLOWED_ORIGINS.items():
        for origin in origins:
            expected_pairs.add((env, origin))

    # Check that all expected pairs are tested
    missing_pairs = expected_pairs - tested_pairs
    assert not missing_pairs, f"Some environment-origin pairs are not covered in tests: {missing_pairs}"

    # Also check for any test cases that don't correspond to allowed origins
    extra_pairs = tested_pairs - expected_pairs
    assert not extra_pairs, f"Some test cases don't correspond to allowed origins: {extra_pairs}"


@pytest.mark.parametrize("env", list(ALLOWED_ORIGINS.keys()))
def test_cors_headers_not_set_for_invalid_origins_parametrized(notify_api, env):
    # Save the original environment and config
    original_env = os.environ.get("NOTIFY_ENVIRONMENT")
    original_config = notify_api.config.get("NOTIFY_ENVIRONMENT")

    try:
        # Set environment for test
        os.environ["NOTIFY_ENVIRONMENT"] = env
        notify_api.config["NOTIFY_ENVIRONMENT"] = env

        with notify_api.test_request_context():
            with notify_api.test_client() as client:
                response = client.get(
                    path="/v2/notifications",
                    headers=[("Origin", get_invalid_origin())],
                )

                assert response.status_code == 401
                assert "Access-Control-Allow-Origin" not in response.headers
    finally:
        # Restore original environment and config
        if original_env is None:
            if "NOTIFY_ENVIRONMENT" in os.environ:
                del os.environ["NOTIFY_ENVIRONMENT"]
        else:
            os.environ["NOTIFY_ENVIRONMENT"] = original_env

        notify_api.config["NOTIFY_ENVIRONMENT"] = original_config
