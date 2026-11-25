import base64
import subprocess
import sys
from copy import deepcopy
from email import message_from_string
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from jsonschema import ValidationError

from app import aws_ses_client
from app.clients.email.aws_ses import AwsSesClientException
from app.delivery import send_to_providers
from app.exceptions import (
    DocumentDownloadException,
    MalwareDetectedException,
    MalwareScanInProgressException,
    NotificationTechnicalFailureException,
)
from app.inline_images import get_inline_image_mime_type, is_service_allowed_inline_images
from app.models import Service, ServicePermission
from app.notifications.validators import validate_inline_image_placeholders
from app.schema_validation import validate
from app.schema_validation.definitions import email_personalisation, personalisation
from app.v2.errors import BadRequestError
from app.v2.notifications import post_notifications
from app.v2.notifications.notification_schemas import post_email_request, post_sms_request
from app.v2.notifications.post_notifications import process_document_uploads

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9ZkAAAAASUVORK5CYII=")


@pytest.fixture
def inline_upload():
    return {
        "chart": {
            "file": base64.b64encode(PNG).decode(),
            "filename": "chart.png",
            "sending_method": "inline",
            "alt_text": "Usage chart",
        }
    }


def validate_upload(values):
    return validate({"personalisation": values}, {"type": "object", "properties": {"personalisation": email_personalisation}})


def test_flag_defaults_to_disabled():
    from app.config import Config

    assert Config.FF_ENABLE_INLINE_IMAGES is False
    assert Config.INLINE_IMAGE_SERVICE_IDS == []


@pytest.mark.parametrize("csv_value,expected", [("", []), (" , first-id,  second-id , , ", ["first-id", "second-id"])])
def test_inline_service_ids_parse_csv(monkeypatch, csv_value, expected):
    import json

    monkeypatch.setenv("INLINE_IMAGE_SERVICE_IDS", csv_value)
    output = subprocess.check_output(
        [sys.executable, "-c", "import json; from app.config import Config; print(json.dumps(Config.INLINE_IMAGE_SERVICE_IDS))"],
        text=True,
    )
    assert json.loads(output) == expected


@pytest.mark.parametrize(
    "enabled,listed,expected", [(False, False, False), (False, True, False), (True, False, False), (True, True, True)]
)
def test_inline_images_require_flag_and_service_allowlist(notify_api, monkeypatch, enabled, listed, expected):
    service_id = uuid4()
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", enabled)
    monkeypatch.setitem(notify_api.config, "INLINE_IMAGE_SERVICE_IDS", [str(service_id)] if listed else [])
    assert is_service_allowed_inline_images(service_id) is expected
    assert is_service_allowed_inline_images(str(service_id)) is expected
    assert is_service_allowed_inline_images(uuid4()) is False


@pytest.mark.parametrize("simulated", [True, False])
def test_unlisted_service_rejected_before_any_upload(notify_api, monkeypatch, mocker, inline_upload, simulated):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", True)
    monkeypatch.setitem(notify_api.config, "INLINE_IMAGE_SERVICE_IDS", [])
    service = SimpleNamespace(id=uuid4())
    upload = mocker.patch("app.v2.notifications.post_notifications.document_download_client.upload_document")
    personalisation = {"attachment": {"file": PNG, "sending_method": "attach", "filename": "file.png"}, **inline_upload}
    with pytest.raises(BadRequestError, match="not enabled for this service") as error:
        process_document_uploads(personalisation, service, simulated, "template-id")
    assert error.value.status_code == 403
    upload.assert_not_called()


def test_allowlist_does_not_restrict_ordinary_attachments(notify_api, monkeypatch):
    monkeypatch.setitem(notify_api.config, "INLINE_IMAGE_SERVICE_IDS", [])
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", False)
    post_notifications.check_inline_image_service_permission({"file": {"file": PNG, "sending_method": "attach"}}, uuid4())


def test_enabled_flag_requires_matching_renderer(monkeypatch):
    from flask import Flask
    from notifications_utils.template import HTMLEmailTemplate

    from app import create_app

    monkeypatch.setattr(HTMLEmailTemplate, "supports_inline_images", False, raising=False)
    with pytest.raises(RuntimeError, match="notification-utils release"):
        create_app(Flask("inline-image-test"), config=SimpleNamespace(FF_ENABLE_INLINE_IMAGES=True))


def test_other_personalisation_schemas_do_not_accept_inline_uploads(inline_upload):
    with pytest.raises(ValidationError, match="not one of"):
        validate({"personalisation": inline_upload}, {"properties": {"personalisation": personalisation}})


def test_inline_upload_rejected_when_disabled(notify_api, monkeypatch, inline_upload):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", False)
    with pytest.raises(ValidationError, match="Inline images are not enabled"):
        validate_upload(inline_upload)


def test_inline_upload_is_decoded_and_validated(notify_api, monkeypatch, inline_upload):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", True)
    assert validate_upload(inline_upload)["personalisation"]["chart"]["file"] == PNG


def test_email_request_schema_accepts_inline_images(notify_api, monkeypatch, inline_upload):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", True)
    form = {"template_id": str(uuid4()), "email_address": "recipient@example.ca", "personalisation": inline_upload}
    assert validate(form, post_email_request)["personalisation"]["chart"]["file"] == PNG


def test_sms_request_schema_rejects_inline_images(notify_api, monkeypatch, inline_upload):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", True)
    form = {"template_id": str(uuid4()), "phone_number": "+16135551234", "personalisation": inline_upload}
    with pytest.raises(ValidationError, match="not one of"):
        validate(form, post_sms_request)


@pytest.mark.parametrize(
    "changes",
    [
        {"alt_text": None},
        {"alt_text": ""},
        {"alt_text": "  "},
        {"alt_text": "x" * 1001},
        {"filename": None},
        {"file": "not-base64"},
        {"file": base64.b64encode(b"<svg></svg>").decode()},
        {"file": base64.b64encode(b"not an image").decode()},
        {"display_size": "invalid"},
        {"max_width": 0},
        {"max_width": -1},
        {"max_width": True},
        {"max_width": "1200"},
        {"max_width": 1.5},
        {"max_width": None},
        {"max_width": 1200, "display_size": "original"},
        {"max_width": 1200, "display_size": "responsive"},
    ],
)
def test_invalid_inline_uploads_rejected(notify_api, monkeypatch, inline_upload, changes):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", True)
    inline_upload["chart"].update(changes)
    with pytest.raises(ValidationError):
        validate_upload(inline_upload)


@pytest.mark.parametrize("missing", ["alt_text", "filename", "file"])
def test_inline_upload_requires_metadata(notify_api, monkeypatch, inline_upload, missing):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", True)
    del inline_upload["chart"][missing]
    with pytest.raises(ValidationError):
        validate_upload(inline_upload)


@pytest.mark.parametrize("size_limit,succeeds", [(len(PNG) - 1, False), (len(PNG), True)])
def test_inline_images_share_attachment_size_limit(notify_api, monkeypatch, inline_upload, size_limit, succeeds):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", True)
    monkeypatch.setitem(notify_api.config, "ATTACHMENT_SIZE_LIMIT", size_limit)
    if succeeds:
        assert validate_upload(inline_upload)["personalisation"]["chart"]["file"] == PNG
    else:
        with pytest.raises(ValidationError, match="greater than allowed limit"):
            validate_upload(inline_upload)


def test_inline_images_share_attachment_count_limit(notify_api, monkeypatch, inline_upload):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", True)
    monkeypatch.setitem(notify_api.config, "ATTACHMENT_NUM_LIMIT", 1)
    inline_upload["another_chart"] = deepcopy(inline_upload["chart"])
    with pytest.raises(ValidationError, match="File number exceed"):
        validate_upload(inline_upload)


@pytest.mark.parametrize(
    "content,subject,notification_type",
    [
        ("Nothing here", "Subject", "email"),
        ("((chart))", "((chart))", "email"),
        ("Text ((chart))", "Subject", "email"),
        ("[chart](((chart)))", "Subject", "email"),
        ("((chart??yes))", "Subject", "email"),
        ("((chart))", "Subject", "sms"),
    ],
)
def test_invalid_image_placeholders_rejected(inline_upload, content, subject, notification_type):
    with pytest.raises(BadRequestError):
        validate_inline_image_placeholders(SimpleNamespace(content=content, subject=subject), inline_upload, notification_type)


def test_image_placeholder_uses_column_normalisation(inline_upload):
    validate_inline_image_placeholders(SimpleNamespace(content="Chart:\n\n((CHART))\n", subject="Usage"), inline_upload, "email")


@pytest.mark.parametrize("simulated", [True, False])
@pytest.mark.parametrize("display_size", [None, "responsive", "original"])
def test_inline_upload_reuses_attachment_storage(notify_api, monkeypatch, mocker, inline_upload, simulated, display_size):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", True)
    inline_upload["chart"]["file"] = PNG
    if display_size is not None:
        inline_upload["chart"]["display_size"] = display_size
    original = deepcopy(inline_upload)
    service = SimpleNamespace(id="service-id", permissions=[SimpleNamespace(permission="upload_document")])
    monkeypatch.setitem(notify_api.config, "INLINE_IMAGE_SERVICE_IDS", [str(service.id)])
    mocker.patch("app.v2.notifications.post_notifications.authenticated_service", service)
    upload = mocker.patch("app.v2.notifications.post_notifications.document_download_client.upload_document")
    upload.return_value = {
        "document": {"id": "document-id", "sending_method": "attach", "filename": "chart.png", "mime_type": "image/png"}
    }
    mocker.patch("app.v2.notifications.post_notifications.save_stats_for_attachments")

    result = process_document_uploads(inline_upload, service, simulated, "template-id")
    metadata = result["chart"]["document"]["inline_image"]
    assert metadata["alt_text"] == "Usage chart"
    assert len(metadata["content_id"]) == 32
    if display_size is not None:
        assert metadata["display_size"] == display_size
    else:
        assert "display_size" not in metadata
    assert inline_upload == original
    if simulated:
        upload.assert_not_called()
    else:
        upload.assert_called_once_with(service.id, {"file": PNG, "filename": "chart.png", "sending_method": "attach"})


def test_inline_upload_requires_document_permission(notify_api, monkeypatch, mocker, inline_upload):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", True)
    service = SimpleNamespace(id="service-id", permissions=[])
    monkeypatch.setitem(notify_api.config, "INLINE_IMAGE_SERVICE_IDS", [str(service.id)])
    mocker.patch("app.v2.notifications.post_notifications.authenticated_service", service)
    upload = mocker.patch("app.v2.notifications.post_notifications.document_download_client.upload_document")
    with pytest.raises(BadRequestError):
        process_document_uploads(inline_upload, service, False, "template-id")
    upload.assert_not_called()


@pytest.mark.parametrize("simulated", [False, True])
@pytest.mark.parametrize("max_width", [1, 1200, 1200.0])
def test_inline_max_width_survives_upload(notify_api, monkeypatch, mocker, inline_upload, simulated, max_width):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", True)
    inline_upload["chart"]["max_width"] = max_width
    values = validate_upload(inline_upload)["personalisation"]
    service = SimpleNamespace(id="service-id", permissions=[SimpleNamespace(permission="upload_document")])
    monkeypatch.setitem(notify_api.config, "INLINE_IMAGE_SERVICE_IDS", [str(service.id)])
    mocker.patch("app.v2.notifications.post_notifications.authenticated_service", service)
    upload = mocker.patch("app.v2.notifications.post_notifications.document_download_client.upload_document")
    upload.return_value = {
        "document": {"id": "document-id", "sending_method": "attach", "filename": "chart.png", "mime_type": "image/png"}
    }
    mocker.patch("app.v2.notifications.post_notifications.save_stats_for_attachments")
    result = process_document_uploads(values, service, simulated, "template-id")
    assert result["chart"]["document"]["inline_image"]["max_width"] == max_width
    assert isinstance(result["chart"]["document"]["inline_image"]["max_width"], int)
    assert values["chart"]["max_width"] == max_width
    if simulated:
        upload.assert_not_called()
    else:
        upload.assert_called_once_with(service.id, {"file": PNG, "filename": "chart.png", "sending_method": "attach"})


@pytest.mark.parametrize("with_attachment", [False, True])
def test_ses_inline_image_mime_structure(notify_api, monkeypatch, mocker, with_attachment):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", True)
    client = mocker.patch.object(aws_ses_client, "_client", create=True)
    mocker.patch.object(aws_ses_client, "statsd_client", create=True)
    attachments = [{"data": b"file", "name": "file.txt"}] if with_attachment else []
    aws_ses_client.send_email(
        "from@example.ca",
        "to@example.ca",
        "Usage",
        "Usage chart",
        html_body='<p><img src="cid:chart-123" alt="Usage chart"></p>',
        attachments=attachments,
        inline_images=[{"data": PNG, "name": "chart.png", "mime_type": "image/png", "content_id": "chart-123"}],
    )
    message = message_from_string(client.send_raw_email.call_args.kwargs["RawMessage"]["Data"])
    alternative = message.get_payload(0) if with_attachment else message
    assert message.get_content_type() == ("multipart/mixed" if with_attachment else "multipart/alternative")
    assert alternative.get_content_type() == "multipart/alternative"
    assert alternative.get_payload(0).get_content_type() == "text/plain"
    related = alternative.get_payload(1)
    assert related.get_content_type() == "multipart/related"
    assert related.get_payload(0).get_content_type() == "text/html"
    image = related.get_payload(1)
    assert image.get_content_type() == "image/png"
    assert len(image.get_all("Content-Type")) == 1
    assert image["Content-ID"] == "<chart-123>"
    assert image.get_content_disposition() == "inline"
    assert image.get_payload(decode=True) == PNG
    if with_attachment:
        assert message.get_payload(1).get_content_disposition() == "attachment"


@pytest.mark.parametrize(
    "enabled,html_body,changes",
    [
        (False, "<p>Chart</p>", {}),
        (True, "", {}),
        (True, "<p>Chart</p>", {"content_id": "x\r\nInjected: true"}),
        (True, "<p>Chart</p>", {"data": b"not an image"}),
        (True, "<p>Chart</p>", {"mime_type": "image/jpeg"}),
    ],
)
def test_ses_rejects_invalid_inline_images(notify_api, monkeypatch, mocker, enabled, html_body, changes):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", enabled)
    client = mocker.patch.object(aws_ses_client, "_client", create=True)
    mocker.patch.object(aws_ses_client, "statsd_client", create=True)
    image = {"data": PNG, "name": "chart.png", "mime_type": "image/png", "content_id": "chart-123", **changes}
    with pytest.raises(AwsSesClientException):
        aws_ses_client.send_email("from@example.ca", "to@example.ca", "Usage", "Usage chart", html_body, inline_images=[image])
    client.send_raw_email.assert_not_called()


def test_supported_image_types():
    assert get_inline_image_mime_type(PNG) == "image/png"
    with pytest.raises(ValueError):
        get_inline_image_mime_type(b"%PDF-1.0")


@pytest.fixture
def delivery(notify_api, monkeypatch, mocker):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", True)
    monkeypatch.setitem(notify_api.config, "SCAN_FOR_PII", False)
    monkeypatch.setitem(notify_api.config, "DOCUMENT_DOWNLOAD_API_HOST", "https://documents.example.ca")
    service = SimpleNamespace(
        id=uuid4(),
        active=True,
        has_permission=lambda permission: True,
        research_mode=False,
        sending_domain="example.ca",
        name="Service",
        email_from="service",
    )
    document_id = uuid4()
    monkeypatch.setitem(notify_api.config, "INLINE_IMAGE_SERVICE_IDS", [str(service.id)])
    document = {
        "id": str(document_id),
        "sending_method": "attach",
        "direct_file_url": "https://untrusted.invalid/image?key=abc123",
        "filename": "chart.png",
        "mime_type": "image/png",
        "inline_image": {"content_id": "chart-123", "alt_text": "Usage chart"},
    }
    notification = SimpleNamespace(
        id=uuid4(),
        service=service,
        service_id=service.id,
        status="created",
        personalisation={"chart": {"document": document}},
        template_id=uuid4(),
        template_version=1,
        key_type="normal",
        to="recipient@example.ca",
        reply_to_text=None,
        notification_type="email",
        sent_at=None,
        created_at=None,
    )
    template = SimpleNamespace(content="Your chart:\n\n((chart))", subject="Usage", template_type="email", process_type="normal")
    mocker.patch.object(send_to_providers, "provider_to_use", return_value=aws_ses_client)
    mocker.patch.object(send_to_providers, "dao_get_template_by_id", return_value=template)
    mocker.patch.object(send_to_providers, "_get_template_attachments", return_value=[])
    mocker.patch.object(send_to_providers, "get_html_email_options", return_value={"fip_banner_english": False})
    mocker.patch.object(send_to_providers, "is_service_allowed_html", return_value=False)
    mocker.patch.object(send_to_providers, "update_notification_to_sending")
    mocker.patch.object(send_to_providers, "dao_update_notification")
    mocker.patch.object(send_to_providers, "check_service_over_bounce_rate")
    mocker.patch.object(send_to_providers, "check_service_over_bounce_rate_old")
    mocker.patch.object(send_to_providers, "bounce_rate_client")
    mocker.patch.object(send_to_providers, "statsd_client")
    scan = mocker.patch.object(
        send_to_providers.document_download_client, "check_scan_verdict", return_value=Mock(status_code=200)
    )
    download = mocker.patch.object(send_to_providers, "PoolManager").return_value.request
    download.return_value = SimpleNamespace(status=200, data=PNG)
    client = mocker.patch.object(aws_ses_client, "_client", create=True)
    client.send_raw_email.return_value = {"MessageId": "ses-message-id"}
    mocker.patch.object(aws_ses_client, "statsd_client", create=True)
    return SimpleNamespace(
        notification=notification,
        template=template,
        scan=scan,
        download=download,
        ses=client,
        document=document,
        document_id=document_id,
    )


def test_delivery_renders_and_embeds_scanned_inline_image(delivery):
    original = deepcopy(delivery.notification.personalisation)
    send_to_providers.send_email_to_provider(delivery.notification)
    delivery.scan.assert_called_once_with(delivery.notification.service.id, str(delivery.document_id), "attach")
    delivery.download.assert_called_once_with(
        "GET",
        url=f"https://documents.example.ca/services/{delivery.notification.service.id}/documents/{delivery.document_id}?key=abc123&sending_method=attach",
        redirect=False,
    )
    message = message_from_string(delivery.ses.send_raw_email.call_args.kwargs["RawMessage"]["Data"])
    plain_text = message.get_payload(0).get_payload(decode=True).decode()
    related = message.get_payload(1)
    html = related.get_payload(0).get_payload(decode=True).decode()
    assert "Usage chart" in plain_text
    assert "inline_image" not in plain_text
    assert '<img src="cid:chart-123"' in html
    assert related.get_payload(1).get_payload(decode=True) == PNG
    assert delivery.notification.personalisation == original
    assert delivery.notification.reference == "ses-message-id"


def test_delivery_preserves_original_image_size(delivery):
    delivery.document["inline_image"]["display_size"] = "original"
    send_to_providers.send_email_to_provider(delivery.notification)
    message = message_from_string(delivery.ses.send_raw_email.call_args.kwargs["RawMessage"]["Data"])
    html = message.get_payload(1).get_payload(0).get_payload(decode=True).decode()
    assert 'src="cid:chart-123"' in html
    assert "max-width: none; width: auto;" in html


def test_delivery_preserves_image_max_width(delivery):
    delivery.document["inline_image"]["max_width"] = 1200
    send_to_providers.send_email_to_provider(delivery.notification)
    message = message_from_string(delivery.ses.send_raw_email.call_args.kwargs["RawMessage"]["Data"])
    html = message.get_payload(1).get_payload(0).get_payload(decode=True).decode()
    assert 'src="cid:chart-123"' in html
    assert "max-width: 1200px; width: auto;" in html
    assert "height: auto;" in html


@pytest.mark.parametrize(
    "scan_status,expected_exception",
    [
        (423, MalwareDetectedException),
        (428, MalwareScanInProgressException),
        (408, DocumentDownloadException),
        (422, DocumentDownloadException),
        (500, DocumentDownloadException),
    ],
)
def test_delivery_never_downloads_images_without_a_successful_scan(delivery, scan_status, expected_exception):
    delivery.scan.return_value.status_code = scan_status
    with pytest.raises(expected_exception):
        send_to_providers.send_email_to_provider(delivery.notification)
    delivery.download.assert_not_called()
    delivery.ses.send_raw_email.assert_not_called()


@pytest.mark.parametrize("status", [302, 404, 500])
def test_delivery_does_not_send_on_image_download_failure(delivery, status):
    delivery.download.return_value.status = status
    with pytest.raises(DocumentDownloadException):
        send_to_providers.send_email_to_provider(delivery.notification)
    delivery.ses.send_raw_email.assert_not_called()


def test_delivery_does_not_send_invalid_image_bytes(delivery):
    delivery.download.return_value.data = b"<svg></svg>"
    with pytest.raises(DocumentDownloadException):
        send_to_providers.send_email_to_provider(delivery.notification)
    delivery.ses.send_raw_email.assert_not_called()


@pytest.mark.parametrize("enabled,permitted", [(False, True), (True, False)])
def test_delivery_checks_feature_flag_and_permission(delivery, notify_api, monkeypatch, enabled, permitted):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", enabled)
    delivery.notification.service.has_permission = lambda permission: permitted
    with pytest.raises(NotificationTechnicalFailureException):
        send_to_providers.send_email_to_provider(delivery.notification)
    delivery.scan.assert_not_called()
    delivery.download.assert_not_called()
    delivery.ses.send_raw_email.assert_not_called()


def test_delivery_rechecks_service_allowlist(delivery, notify_api, monkeypatch):
    monkeypatch.setitem(notify_api.config, "INLINE_IMAGE_SERVICE_IDS", [])
    with pytest.raises(NotificationTechnicalFailureException):
        send_to_providers.send_email_to_provider(delivery.notification)
    delivery.scan.assert_not_called()
    delivery.download.assert_not_called()
    delivery.ses.send_raw_email.assert_not_called()


def test_delivery_embeds_multiple_images(delivery):
    second = deepcopy(delivery.document)
    second["id"] = str(uuid4())
    second["inline_image"]["content_id"] = "chart-456"
    delivery.notification.personalisation["another_chart"] = {"document": second}
    delivery.template.content += "\n\n((another_chart))"
    send_to_providers.send_email_to_provider(delivery.notification)
    message = message_from_string(delivery.ses.send_raw_email.call_args.kwargs["RawMessage"]["Data"])
    related = message.get_payload(1)
    assert [part["Content-ID"] for part in related.get_payload()[1:]] == ["<chart-123>", "<chart-456>"]
    html = related.get_payload(0).get_payload(decode=True).decode()
    assert 'src="cid:chart-123"' in html
    assert 'src="cid:chart-456"' in html


def test_ses_rejects_duplicate_image_content_ids(notify_api, monkeypatch, mocker):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", True)
    client = mocker.patch.object(aws_ses_client, "_client", create=True)
    mocker.patch.object(aws_ses_client, "statsd_client", create=True)
    image = {"data": PNG, "name": "chart.png", "mime_type": "image/png", "content_id": "chart-123"}
    with pytest.raises(AwsSesClientException, match="must be unique"):
        aws_ses_client.send_email(
            "from@example.ca", "to@example.ca", "Usage", "Usage chart", "<p>Chart</p>", inline_images=[image, image]
        )
    client.send_raw_email.assert_not_called()


@pytest.mark.parametrize("simulated,scheduled", [(False, False), (False, True), (True, False)])
def test_image_metadata_survives_queueing_and_scheduling(notify_api, monkeypatch, mocker, inline_upload, simulated, scheduled):
    monkeypatch.setitem(notify_api.config, "FF_ENABLE_INLINE_IMAGES", True)
    service = Service(id=uuid4(), permissions=[ServicePermission(permission="upload_document")])
    monkeypatch.setitem(notify_api.config, "INLINE_IMAGE_SERVICE_IDS", [str(service.id)])
    api_key = SimpleNamespace(id=uuid4(), key_type="normal")
    template = SimpleNamespace(id=uuid4(), version=1, template_type="email", process_type="normal")
    mocker.patch.object(post_notifications, "authenticated_service", service)
    mocker.patch.object(post_notifications, "validate_and_format_recipient", return_value="recipient@example.ca")
    mocker.patch.object(post_notifications, "simulated_recipient", return_value=simulated)
    mocker.patch.object(post_notifications, "update_last_used_api_key")
    mocker.patch.object(post_notifications, "save_stats_for_attachments")
    upload = mocker.patch.object(post_notifications.document_download_client, "upload_document")
    upload.return_value = {
        "document": {
            "id": str(uuid4()),
            "sending_method": "attach",
            "filename": "chart.png",
            "mime_type": "image/png",
        }
    }
    publish = mocker.patch.object(post_notifications, "triage_notification_to_queues")
    persist = mocker.patch.object(post_notifications, "persist_scheduled_one_off_notification")
    inline_upload["chart"]["file"] = PNG
    form = {"email_address": "recipient@example.ca", "personalisation": inline_upload}
    if scheduled:
        form["scheduled_for"] = "2026-11-14T12:00:00Z"
    notification = post_notifications.process_sms_or_email_notification(
        form=form,
        notification_type="email",
        api_key=api_key,
        template=template,
        service=service,
    )
    metadata = notification.personalisation["chart"]["document"]["inline_image"]
    assert metadata["alt_text"] == "Usage chart"
    assert len(metadata["content_id"]) == 32
    assert "file" not in notification.personalisation["chart"]
    if simulated:
        upload.assert_not_called()
        publish.assert_not_called()
        persist.assert_not_called()
    elif scheduled:
        publish.assert_not_called()
        persist.assert_called_once_with(notification, form["scheduled_for"])
    else:
        persist.assert_not_called()
        signed = publish.call_args.args[1]
        payload = post_notifications.signer_notification.verify(signed)
        assert payload["personalisation"]["chart"]["document"]["inline_image"] == metadata
