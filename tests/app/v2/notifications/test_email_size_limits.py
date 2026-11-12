from types import SimpleNamespace

import pytest
from flask import current_app, json
from notifications_python_client.authentication import create_jwt_token
from notifications_utils.template import HTMLEmailTemplate

from app.authentication.auth import AUTH_TYPES
from app.models import EMAIL_TYPE
from app.notifications.validators import _email_content_segments, check_email_csv_rows_size
from app.v2.errors import BadRequestError
from tests import create_authorization_header
from tests.app.conftest import create_sample_job
from tests.app.db import create_template

SIMULATED_EMAIL = "simulate-delivered@notification.canada.ca"
STATIC_LIMIT = 50_000
PERSONALISATION_LIMIT = 50_000


class TestEmailSizeLimits:
    """Email size limits for template creation, template update, and v2 send.

    Limits under test:
    - Static template content: EMAIL_CHAR_COUNT_LIMIT (50,000 characters).
    - Personalisation values combined: PERSONALISATION_SIZE_LIMIT (50,000).
    - Rendered email body (template + variables): EMAIL_CHAR_COUNT_LIMIT (50,000).
    """

    @pytest.fixture
    def mock_send_limits(self, mocker):
        annual = {
            "total_email_fiscal_year_to_yesterday": 0,
            "total_sms_fiscal_year_to_yesterday": 0,
            "total_sms_billable_units_fiscal_year_to_yesterday": 0,
        }
        mocker.patch("app.v2.notifications.post_notifications.get_annual_limit_notifications_v2", return_value=annual)
        mocker.patch("app.notifications.validators.get_annual_limit_notifications_v2", return_value=annual)
        return mocker.patch("app.email_normal_publish.publish")

    @staticmethod
    def _post_template(client, api_key, name, content, category):
        return client.post(
            "/v2/manage-template",
            data=json.dumps(
                {
                    "name": name,
                    "template_type": EMAIL_TYPE,
                    "subject": "Subject",
                    "content": content,
                    "template_category_id": str(category.id),
                }
            ),
            headers=[("Content-Type", "application/json"), create_authorization_header(api_key=api_key)],
        )

    @staticmethod
    def _send(client, service, template_id, personalisation, email_address=None):
        return client.post(
            path="v2/notifications/email",
            data=json.dumps(
                {
                    "email_address": email_address or service.users[0].email_address,
                    "template_id": str(template_id),
                    "personalisation": personalisation,
                }
            ),
            headers=[
                ("Content-Type", "application/json"),
                create_authorization_header(service_id=service.id),
            ],
        )

    # Template creation and update (static size)

    def test_create_template_over_50k_chars_returns_400(
        self, client, sample_template_category, create_api_key_with_manage_api_perm
    ):
        response = self._post_template(
            client,
            create_api_key_with_manage_api_perm,
            "Too big",
            "A" * (STATIC_LIMIT + 1),
            sample_template_category,
        )

        assert response.status_code == 400
        assert "greater than the limit" in response.get_data(as_text=True)

    def test_create_template_at_50k_chars_returns_201(
        self, client, sample_template_category, create_api_key_with_manage_api_perm
    ):
        response = self._post_template(
            client,
            create_api_key_with_manage_api_perm,
            "Exactly at limit",
            "A" * STATIC_LIMIT,
            sample_template_category,
        )

        assert response.status_code == 201

    def test_patch_template_over_50k_chars_returns_400(self, client, sample_service, create_api_key_with_manage_api_perm):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="Short body")

        response = client.patch(
            f"/v2/manage-template/{template.id}",
            data=json.dumps({"content": "A" * (STATIC_LIMIT + 1)}),
            headers=[
                ("Content-Type", "application/json"),
                create_authorization_header(api_key=create_api_key_with_manage_api_perm),
            ],
        )

        assert response.status_code == 400

    # Send: personalisation (variable) size

    def test_send_personalisation_combined_over_50000_returns_400(self, client, sample_service, mock_send_limits):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((a))((b))")
        personalisation = {"a": "A" * 25_000, "b": "B" * 25_001}

        response = self._send(client, sample_service, template.id, personalisation)

        assert response.status_code == 400
        assert not mock_send_limits.called

    def test_send_personalisation_at_50000_returns_201(self, client, sample_service, mock_send_limits):
        # The value is unused by the template, so the rendered body stays small.
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="Hello")

        response = self._send(client, sample_service, template.id, {"payload": "A" * PERSONALISATION_LIMIT})

        assert response.status_code == 201
        assert mock_send_limits.called

    # Send: rendered body size (static + variables)

    def test_send_rendered_body_at_50000_chars_returns_201(self, client, sample_service, mock_send_limits):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((payload))")

        response = self._send(client, sample_service, template.id, {"payload": "A" * STATIC_LIMIT})

        assert response.status_code == 201
        assert mock_send_limits.called

    def test_send_single_variable_rendered_over_50000_chars_returns_400(self, client, sample_service, mock_send_limits):
        # Personalisation is at its limit, but one static character puts the rendered body over it.
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="S((payload))")

        response = self._send(client, sample_service, template.id, {"payload": "A" * PERSONALISATION_LIMIT})

        assert response.status_code == 400
        assert not mock_send_limits.called

    def test_send_template_plus_personalisation_at_50000_returns_201(self, client, sample_service, mock_send_limits):
        # Static text (25,000) and personalisation (25,000) combine to exactly 50,000 rendered characters.
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="S" * 25_000 + "((payload))")

        response = self._send(client, sample_service, template.id, {"payload": "A" * 25_000})

        assert response.status_code == 201
        assert mock_send_limits.called

    def test_send_template_plus_personalisation_over_50000_returns_400(self, client, sample_service, mock_send_limits):
        # Static text (26,000) and personalisation (26,000) are each under their limits.
        # Combined rendered size is 52,000, which is over 50,000.
        template = create_template(
            sample_service,
            template_type=EMAIL_TYPE,
            content="S" * 26_000 + "((payload))",
        )

        response = self._send(client, sample_service, template.id, {"payload": "A" * 26_000})

        assert response.status_code == 400
        assert not mock_send_limits.called

    def test_send_repeated_variable_rendered_over_50000_returns_400(self, client, sample_service, mock_send_limits):
        # One 26,000-char value is used twice. Personalisation counts it once (26,000),
        # but the rendered body is about 52,000 characters.
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((payload))\nX\n((payload))")

        response = self._send(client, sample_service, template.id, {"payload": "A" * 26_000})

        assert response.status_code == 400
        assert not mock_send_limits.called

    def test_send_simulated_recipient_oversized_rendered_body_returns_400(self, client, sample_service, mock_send_limits):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((payload))\nX\n((payload))")

        response = self._send(client, sample_service, template.id, {"payload": "A" * 26_000}, email_address=SIMULATED_EMAIL)

        assert response.status_code == 400

    # Admin send path (service/<id>/send-notification) also calls validate_template

    @pytest.fixture
    def mock_admin_send(self, mocker):
        return mocker.patch("app.service.send_notification.send_notification_to_queue")

    @staticmethod
    def _admin_send(client, service, template_id, personalisation):
        token = create_jwt_token(
            current_app.config["ADMIN_CLIENT_SECRET"], client_id=current_app.config["ADMIN_CLIENT_USER_NAME"]
        )
        return client.post(
            f"/service/{service.id}/send-notification",
            json={
                "to": service.users[0].email_address,
                "template_id": str(template_id),
                "created_by": str(service.users[0].id),
                "personalisation": personalisation,
            },
            headers=[("Content-Type", "application/json"), ("Authorization", f"{AUTH_TYPES[0][0]} {token}")],
        )

    def test_admin_send_rendered_body_over_50000_returns_400(self, client, sample_service, mock_admin_send):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((payload))\nX\n((payload))")

        response = self._admin_send(client, sample_service, template.id, {"payload": "A" * 26_000})

        assert response.status_code == 400
        assert "greater than the limit" in response.get_data(as_text=True)
        assert not mock_admin_send.called

    def test_admin_send_rendered_body_at_50000_returns_201(self, client, sample_service, mock_admin_send):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((payload))")

        response = self._admin_send(client, sample_service, template.id, {"payload": "A" * STATIC_LIMIT})

        assert response.status_code == 201
        assert mock_admin_send.called

    # Bulk send (POST /v2/notifications/bulk) runs the same limits per CSV row

    @pytest.fixture
    def mock_bulk_job(self, mocker, notify_db, notify_db_session):
        job = create_sample_job(notify_db=notify_db, notify_db_session=notify_db_session)
        return mocker.patch("app.v2.notifications.post_notifications.create_bulk_job", return_value=job)

    @staticmethod
    def _post_bulk(client, service, template_id, rows):
        return client.post(
            "/v2/notifications/bulk",
            data=json.dumps({"name": "job", "template_id": str(template_id), "rows": rows}),
            headers=[("Content-Type", "application/json"), create_authorization_header(service_id=service.id)],
        )

    def test_bulk_row_rendered_body_over_50000_returns_400(self, client, sample_service, mock_bulk_job):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((payload))\nX\n((payload))")

        response = self._post_bulk(
            client, sample_service, template.id, [["email address", "payload"], ["a@example.ca", "A" * 26_000]]
        )

        assert response.status_code == 400
        assert "Row 1" in response.get_data(as_text=True)
        assert not mock_bulk_job.called

    def test_bulk_row_personalisation_over_50000_returns_400(self, client, sample_service, mock_bulk_job):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((a))((b))")

        response = self._post_bulk(
            client,
            sample_service,
            template.id,
            [["email address", "a", "b"], ["a@example.ca", "A" * 26_000, "B" * 26_000]],
        )

        assert response.status_code == 400
        assert "Row 1" in response.get_data(as_text=True)
        assert not mock_bulk_job.called

    def test_bulk_rows_at_50000_returns_200(self, client, sample_service, mock_bulk_job):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((payload))")

        address = "a@example.ca"
        response = self._post_bulk(
            client,
            sample_service,
            template.id,
            [["email address", "payload"], [address, "A" * (STATIC_LIMIT - len(address))]],
        )

        assert response.status_code == 201, response.get_data(as_text=True)
        assert mock_bulk_job.called

    # CSV job route (POST /service/<id>/job) reads an uploaded file from S3

    @staticmethod
    def _create_job_from_csv(client, mocker, service, template, csv_text):
        mocker.patch(
            "app.job.rest.get_job_metadata_from_s3",
            return_value={
                "template_id": str(template.id),
                "original_file_name": "big.csv",
                "notification_count": "1",
                "valid": "True",
            },
        )
        mocker.patch("app.job.rest.get_job_from_s3", return_value=csv_text)
        mocker.patch(
            "app.notifications.validators.get_annual_limit_notifications_v2",
            return_value={"total_email_fiscal_year_to_yesterday": 0, "total_sms_fiscal_year_to_yesterday": 0},
        )
        return client.post(
            f"/service/{service.id}/job",
            data=json.dumps({"id": "7b2f8a52-3c1e-4d7a-9e51-2f6a0c9d4b10", "created_by": str(service.users[0].id)}),
            headers=[("Content-Type", "application/json"), create_authorization_header()],
        )

    def test_csv_job_row_rendered_body_over_50000_returns_400(self, client, mocker, sample_service):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((payload))\nX\n((payload))")
        mock_create = mocker.patch("app.job.rest.dao_create_job")
        csv_text = f"email address,payload\na@example.ca,{'A' * 26_000}\n"

        response = self._create_job_from_csv(client, mocker, sample_service, template, csv_text)

        assert response.status_code == 400
        assert "Row 1" in response.get_data(as_text=True)
        assert not mock_create.called

    def test_csv_job_row_at_50000_is_accepted(self, client, mocker, sample_service):
        template = create_template(sample_service, template_type=EMAIL_TYPE, content="((payload))")
        mock_create = mocker.patch("app.job.rest.dao_create_job")
        mocker.patch("app.celery.tasks.process_job.apply_async")
        address = "a@example.ca"
        csv_text = f"email address,payload\n{address},{'A' * (STATIC_LIMIT - len(address))}\n"

        response = self._create_job_from_csv(client, mocker, sample_service, template, csv_text)

        assert response.status_code == 201, response.get_data(as_text=True)
        assert mock_create.called

    # Bulk row check counts each row like HTMLEmailTemplate.content_count without building the template.

    @pytest.fixture
    def app_ctx(self, notify_api):
        with notify_api.app_context():
            yield

    @staticmethod
    def _csv_stub(content, rows):
        template = SimpleNamespace(template_type=EMAIL_TYPE, content=content, subject="Subject")
        recipient_csv = SimpleNamespace(rows=[SimpleNamespace(index=i, personalisation=values) for i, values in enumerate(rows)])
        return recipient_csv, template

    @pytest.mark.parametrize(
        "content, values",
        [
            ("((a))((a))((b))", {"a": "x" * 20_000, "b": "y" * 10_001}),
            ("Hi ((name))\n\n* ((item))\n* ((item))", {"name": "x" * 25_000, "item": "y" * 12_500}),
            ("((cond??line one\nline two))" + "S" * 49_990, {"cond": "yes"}),
        ],
    )
    def test_csv_row_limit_matches_html_email_template_count(self, app_ctx, content, values):
        exact = HTMLEmailTemplate({"content": content, "subject": "s", "template_type": EMAIL_TYPE}, values=values).content_count
        recipient_csv, template = self._csv_stub(content, [values])

        if exact > STATIC_LIMIT:
            with pytest.raises(BadRequestError):
                check_email_csv_rows_size(recipient_csv, template)
        else:
            check_email_csv_rows_size(recipient_csv, template)

    def test_csv_rows_do_not_build_html_email_template(self, app_ctx, mocker):
        spy = mocker.patch("app.notifications.validators.HTMLEmailTemplate", wraps=HTMLEmailTemplate)
        parse_spy = mocker.patch("app.notifications.validators._email_content_segments", wraps=_email_content_segments)
        recipient_csv, template = self._csv_stub(
            "S" * 49_900 + " ((First Name)), your order is ((order))\n\n((opt??extra))",
            [{"firstname": f"user{i}", "order": str(i), "opt": None} for i in range(50_000)],
        )

        check_email_csv_rows_size(recipient_csv, template)

        assert spy.call_count == 0
        assert parse_spy.call_count == 1

    def test_csv_row_over_limit_is_rejected(self, app_ctx):
        # Personalisation stays under 50,000 but the repeated variable pushes the rendered body over it.
        recipient_csv, template = self._csv_stub("((a))((a))((a))", [{"a": "x" * 10}, {"a": "x" * 20_000}])

        with pytest.raises(BadRequestError) as exc:
            check_email_csv_rows_size(recipient_csv, template)

        assert "Row 2" in exc.value.message

    def test_csv_row_with_blank_cell_is_still_measured(self, app_ctx):
        # A blank optional cell must not cause the row to be measured as the bare template.
        recipient_csv, template = self._csv_stub(
            "S" * 30_000 + "((name))\n\n((opt??extra))", [{"name": "x" * 25_000, "opt": None}]
        )

        with pytest.raises(BadRequestError):
            check_email_csv_rows_size(recipient_csv, template)

    def test_csv_row_with_mixed_case_placeholder_is_measured(self, app_ctx):
        # RecipientCSV normalises keys ("First Name" -> "firstname").
        recipient_csv, template = self._csv_stub("S" * 30_000 + "((First Name))", [{"firstname": "x" * 25_000}])

        with pytest.raises(BadRequestError):
            check_email_csv_rows_size(recipient_csv, template)

    def test_csv_row_bound_over_limit_but_exact_under_is_accepted(self, app_ctx, mocker):
        body = "B" * 49_999
        recipient_csv, template = self._csv_stub(f"((a??{body}))", [{"a": "x"}])
        assert len(template.content) > STATIC_LIMIT

        check_email_csv_rows_size(recipient_csv, template)
