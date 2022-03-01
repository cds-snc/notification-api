from typing import Any, Dict

import pytest
import requests_mock
from flask import Flask
from requests import HTTPError

from app.clients.zendesk import Zendesk
from app.user.contact_request import ContactRequest


def test_send_ticket_go_live_request(notify_api: Flask):
    def match_json(request):
        expected = {
            "request": {
                "subject": "Support Request",
                "comment": {
                    "body": "t6 just requested to go live.<br><br>"
                    "- Department/org: department_org_name<br>"
                    "- Intended recipients: internal, external, public<br>"
                    "- Purpose: main_use_case<br>"
                    "- Notification types: email, sms<br>"
                    "- Expected monthly volume: 100k+<br>"
                    "---<br>"
                    "http://localhost:6012/services/8624bd36-b70b-4d4b-a459-13e1f4770b92"
                },
                "requester": {"name": "name", "email": "test@email.com"},
                "tags": ["notification_api"],
            }
        }
        json_matches = request.json() == expected

        return json_matches

    with requests_mock.mock() as rmock:
        rmock.request(
            "POST",
            "https://zendesk-test.com/api/v2/requests",
            additional_matcher=match_json,
            status_code=201,
        )
        data: Dict[str, Any] = {
            "email_address": "test@email.com",
            "name": "name",
            "department_org_name": "department_org_name",
            "intended_recipients": "internal, external, public",
            "main_use_case": "main_use_case",
            "friendly_support_type": "Support Request",
            "support_type": "go_live_request",
            "service_name": "t6",
            "service_id": "8624bd36-b70b-4d4b-a459-13e1f4770b92",
            "service_url": "http://localhost:6012/services/8624bd36-b70b-4d4b-a459-13e1f4770b92",
            "notification_types": "email, sms",
            "expected_volume": "100k+",
        }
        with notify_api.app_context():
            Zendesk(ContactRequest(**data)).send_ticket()


def test_send_ticket_branding_request(notify_api: Flask):
    def match_json(request):
        expected = {
            "request": {
                "subject": "Branding request",
                "comment": {
                    "body": "A new logo has been uploaded by name (test@email.com) for the following service:<br>"
                    "- Service id: 8624bd36-b70b-4d4b-a459-13e1f4770b92<br>"
                    "- Service name: t6<br>"
                    "- Logo filename: branding_url<br>"
                    "<hr><br>"
                    "Un nouveau logo a été téléchargé par name (test@email.com) pour le service suivant :<br>"
                    "- Identifiant du service : 8624bd36-b70b-4d4b-a459-13e1f4770b92<br>"
                    "- Nom du service : t6<br>"
                    "- Nom du fichier du logo : branding_url"
                },
                "requester": {"name": "name", "email": "test@email.com"},
                "tags": ["notification_api"],
            }
        }

        json_matches = request.json() == expected

        return json_matches

    with requests_mock.mock() as rmock:
        rmock.request(
            "POST",
            "https://zendesk-test.com/api/v2/requests",
            additional_matcher=match_json,
            status_code=201,
        )
        data: Dict[str, Any] = {
            "email_address": "test@email.com",
            "name": "name",
            "friendly_support_type": "Branding request",
            "support_type": "branding_request",
            "service_name": "t6",
            "service_id": "8624bd36-b70b-4d4b-a459-13e1f4770b92",
            "branding_url": "branding_url",
        }
        with notify_api.app_context():
            Zendesk(ContactRequest(**data)).send_ticket()


def test_send_ticket_other(notify_api: Flask):
    def match_json(request):
        expected = {
            "request": {
                "subject": "Support Request",
                "comment": {"body": ""},
                "requester": {"name": "User/Utilisateur", "email": "test@email.com"},
                "tags": ["notification_api"],
            }
        }

        json_matches = request.json() == expected

        return json_matches

    with requests_mock.mock() as rmock:
        rmock.request(
            "POST",
            "https://zendesk-test.com/api/v2/requests",
            additional_matcher=match_json,
            status_code=201,
        )

        with notify_api.app_context():
            Zendesk(ContactRequest(email_address="test@email.com")).send_ticket()


def test_send_ticket_user_profile(notify_api: Flask):
    def match_json(request):
        expected = {
            "request": {
                "subject": "Support Request",
                "comment": {"body": "<br><br>---<br><br> user_profile"},
                "requester": {"name": "User/Utilisateur", "email": "test@email.com"},
                "tags": ["notification_api"],
            }
        }

        json_matches = request.json() == expected

        return json_matches

    with requests_mock.mock() as rmock:
        rmock.request(
            "POST",
            "https://zendesk-test.com/api/v2/requests",
            additional_matcher=match_json,
            status_code=201,
        )

        with notify_api.app_context():
            Zendesk(
                ContactRequest(
                    email_address="test@email.com",
                    user_profile="user_profile",
                )
            ).send_ticket()


def test_send_ticket_unknown_error(notify_api: Flask):
    def match_json(request):
        expected = {
            "request": {
                "subject": "Support Request",
                "comment": {"body": ""},
                "requester": {"name": "User/Utilisateur", "email": "test@email.com"},
                "tags": ["notification_api"],
            }
        }

        json_matches = request.json() == expected
        return json_matches

    with requests_mock.mock() as rmock:
        rmock.request(
            "POST",
            "https://zendesk-test.com/api/v2/requests",
            additional_matcher=match_json,
            status_code=403,
        )

        with notify_api.app_context():
            with pytest.raises(HTTPError):
                Zendesk(ContactRequest(email_address="test@email.com")).send_ticket()
