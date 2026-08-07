from unittest.mock import Mock

import botocore

from app.models import KEY_TYPE_TEST
from tests.app.db import create_notification, create_template, save_notification


def _client_error(code, message):
    return botocore.exceptions.ClientError(
        {"Error": {"Code": code, "Message": message}},
        "DeleteSuppressedDestination",
    )


def test_remove_email_from_suppression_list(admin_request, sample_service, mocker):
    email_address = "person@example.com"
    template = create_template(sample_service, template_type="email")
    save_notification(
        create_notification(
            template=template,
            to_field=email_address,
            normalised_to=email_address,
        )
    )

    mock_ses_client = Mock()
    mocker.patch("app.service.rest.boto3.client", return_value=mock_ses_client)
    mock_freshdesk = mocker.patch("app.service.rest.Freshdesk")
    mock_freshdesk.return_value.send_ticket.return_value = 201

    response = admin_request.post(
        "service.remove_email_from_suppression_list",
        service_id=sample_service.id,
        _data={
            "email_address": email_address,
            "updated_by_id": str(sample_service.users[0].id),
            "request_details": "Recipient confirmed mailbox is healthy.",
        },
    )

    assert response["data"]["email_address"] == email_address
    mock_ses_client.delete_suppressed_destination.assert_called_once_with(EmailAddress=email_address)
    mock_freshdesk.return_value.send_ticket.assert_called_once_with()

    contact = mock_freshdesk.call_args.args[0]
    assert contact.service_id == str(sample_service.id)
    assert contact.service_name == sample_service.name
    assert "Recipient confirmed mailbox is healthy." in contact.message


def test_remove_email_from_suppression_list_rejects_unknown_recipient(admin_request, sample_service, mocker):
    mock_ses_client = Mock()
    mocker.patch("app.service.rest.boto3.client", return_value=mock_ses_client)

    response = admin_request.post(
        "service.remove_email_from_suppression_list",
        service_id=sample_service.id,
        _data={
            "email_address": "unknown@example.com",
            "updated_by_id": str(sample_service.users[0].id),
        },
        _expected_status=400,
    )

    assert response["message"] == {"email_address": ["You can only remove email addresses your service has previously emailed."]}
    mock_ses_client.delete_suppressed_destination.assert_not_called()


def test_remove_email_from_suppression_list_ignores_test_key_notifications(admin_request, sample_service, mocker):
    email_address = "test-only@example.com"
    template = create_template(sample_service, template_type="email")
    save_notification(
        create_notification(
            template=template,
            to_field=email_address,
            normalised_to=email_address,
            key_type=KEY_TYPE_TEST,
        )
    )

    response = admin_request.post(
        "service.remove_email_from_suppression_list",
        service_id=sample_service.id,
        _data={
            "email_address": email_address,
            "updated_by_id": str(sample_service.users[0].id),
        },
        _expected_status=400,
    )

    assert response["message"] == {"email_address": ["You can only remove email addresses your service has previously emailed."]}


def test_remove_email_from_suppression_list_returns_400_when_not_suppressed(admin_request, sample_service, mocker):
    email_address = "person@example.com"
    template = create_template(sample_service, template_type="email")
    save_notification(
        create_notification(
            template=template,
            to_field=email_address,
            normalised_to=email_address,
        )
    )

    mock_ses_client = Mock()
    mock_ses_client.delete_suppressed_destination.side_effect = _client_error(
        "NotFoundException",
        "The destination does not exist in the suppression list.",
    )
    mocker.patch("app.service.rest.boto3.client", return_value=mock_ses_client)
    mock_freshdesk = mocker.patch("app.service.rest.Freshdesk")

    response = admin_request.post(
        "service.remove_email_from_suppression_list",
        service_id=sample_service.id,
        _data={
            "email_address": email_address,
            "updated_by_id": str(sample_service.users[0].id),
        },
        _expected_status=400,
    )

    assert response["message"] == {"email_address": ["This email address is not currently on the suppression list."]}
    mock_freshdesk.return_value.send_ticket.assert_not_called()
