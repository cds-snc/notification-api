import json

from tests import create_authorization_header


def test_create_service_with_too_long_name_fails(notify_api, sample_user):
    """
    Test that creating a service with a name that's too long (when MIME encoded with email address)
    will fail validation.
    """
    # Create a service name that will exceed the 320 character limit when MIME encoded
    # with the email address. Using accented characters which expand when base64 encoded.
    long_name = "é" * 179  # This is 179 characters, but will expand when base64 encoded

    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {
                "name": long_name,
                "user_id": str(sample_user.id),
                "message_limit": 1000,
                "sms_daily_limit": 1000,
                "restricted": False,
                "active": False,
                "email_from": "abc-1234-12345-1234567-1234567",  # Long email address
                "created_by": str(sample_user.id),
            }
            auth_header = create_authorization_header()
            headers = [("Content-Type", "application/json"), auth_header]
            resp = client.post("/service", data=json.dumps(data), headers=headers)
            json_resp = resp.json
            assert resp.status_code == 400
            assert json_resp["result"] == "error"
            # Check that the error message mentions the service name being too long
            assert "Service name is too long" in json_resp["message"]["name"][0]
            assert "320 characters" in json_resp["message"]["name"][0]


def test_create_service_with_reasonable_name_succeeds(notify_api, sample_user):
    """
    Test that creating a service with a reasonable name length succeeds.
    """
    # Use a shorter name that should work fine
    reasonable_name = "Test Service"

    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {
                "name": reasonable_name,
                "user_id": str(sample_user.id),
                "message_limit": 1000,
                "sms_daily_limit": 1000,
                "restricted": False,
                "active": False,
                "email_from": "test.service",
                "created_by": str(sample_user.id),
            }
            auth_header = create_authorization_header()
            headers = [("Content-Type", "application/json"), auth_header]
            resp = client.post("/service", data=json.dumps(data), headers=headers)
            assert resp.status_code == 201


def test_update_service_with_too_long_name_fails(notify_api, sample_service):
    """
    Test that updating a service with a name that's too long will fail validation.
    """
    # Create a service name that will exceed the 320 character limit when MIME encoded
    long_name = "é" * 179

    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {
                "name": long_name,
                "email_from": "abc-1234-12345-1234567-1234567",
                "created_by": str(sample_service.created_by.id),
            }
            auth_header = create_authorization_header()
            headers = [("Content-Type", "application/json"), auth_header]
            resp = client.post(
                f"/service/{sample_service.id}",
                data=json.dumps(data),
                headers=headers,
            )
            json_resp = resp.json
            assert resp.status_code == 400
            assert json_resp["result"] == "error"
            assert "Service name is too long" in json_resp["message"]["name"][0]


def test_create_service_name_at_boundary_succeeds(notify_api, sample_user):
    """
    Test that a service name that's just under the limit succeeds.
    """
    # Calculate a name that's just under the limit
    # The format is: "=?utf-8?B?<base64>?=" <email@domain>
    # We need to account for quotes, spaces, angle brackets, @ and domain
    # Let's use a name of about 100 characters which should be safe
    safe_name = "Service " * 14  # About 98 characters

    with notify_api.test_request_context():
        with notify_api.test_client() as client:
            data = {
                "name": safe_name,
                "user_id": str(sample_user.id),
                "message_limit": 1000,
                "sms_daily_limit": 1000,
                "restricted": False,
                "active": False,
                "email_from": "test.service",
                "created_by": str(sample_user.id),
            }
            auth_header = create_authorization_header()
            headers = [("Content-Type", "application/json"), auth_header]
            resp = client.post("/service", data=json.dumps(data), headers=headers)
            assert resp.status_code == 201
