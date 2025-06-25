from tests import create_authorization_header


def test_cors_headers_set_on_api_request(notify_api):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            allow_headers = "Content-Type,Authorization"
            allow_methods = "GET,PUT,POST,DELETE"

            # Making a GET request to healthcheck which should be unrestricted
            response = client.get(
                path="/v2/notifications",
                headers=[
                    ("Origin", "https://documentation.notification.canada.ca"),
                ],
            )

            assert response.status_code == 401
            assert response.headers["Access-Control-Allow-Origin"] == "https://documentation.notification.canada.ca"
            assert response.headers["Access-Control-Allow-Headers"] == allow_headers
            assert response.headers["Access-Control-Allow-Methods"] == allow_methods


def test_cors_headers_not_set_for_invalid_origins(notify_api):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            # Making a GET request with an unauthorized origin
            response = client.get(
                path="/v2/notifications",
                headers=[
                    ("Origin", "https://malicious-site.com"),
                ],
            )

            assert response.status_code == 401
            assert "Access-Control-Allow-Origin" not in response.headers


def test_cors_headers_work_with_options_method(notify_api):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            allow_headers = "Content-Type,Authorization"
            allow_methods = "GET,PUT,POST,DELETE"

            # Making an OPTIONS request to healthcheck
            response = client.options(
                path="/v2/notifications",
                headers=[
                    ("Origin", "https://documentation.notification.canada.ca"),
                ],
            )

            assert response.status_code == 200
            assert response.headers["Access-Control-Allow-Origin"] == "https://documentation.notification.canada.ca"
            assert response.headers["Access-Control-Allow-Headers"] == allow_headers
            assert response.headers["Access-Control-Allow-Methods"] == allow_methods


def test_cors_headers_with_auth_protected_route(notify_api, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            allow_headers = "Content-Type,Authorization"
            allow_methods = "GET,PUT,POST,DELETE"

            # Create auth header
            auth_header = create_authorization_header()

            # Making a GET request to an auth-protected endpoint
            response = client.get(
                path=f"/service/{sample_service.id}",
                headers=[("Origin", "https://documentation.notification.canada.ca"), auth_header],
            )

            assert response.status_code == 200
            assert response.headers["Access-Control-Allow-Origin"] == "https://documentation.notification.canada.ca"
            assert response.headers["Access-Control-Allow-Headers"] == allow_headers
            assert response.headers["Access-Control-Allow-Methods"] == allow_methods


def test_cors_options_with_auth_protected_route(notify_api, sample_service):
    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            allow_headers = "Content-Type,Authorization"
            allow_methods = "GET,PUT,POST,DELETE"

            # Making an OPTIONS request to an auth-protected endpoint
            # Note: OPTIONS requests should work without authentication
            response = client.options(
                path="/v2/notifications",
                headers=[
                    ("Origin", "https://documentation.notification.canada.ca"),
                ],
            )

            assert response.status_code == 200
            assert response.headers["Access-Control-Allow-Origin"] == "https://documentation.notification.canada.ca"
            assert response.headers["Access-Control-Allow-Headers"] == allow_headers
            assert response.headers["Access-Control-Allow-Methods"] == allow_methods
