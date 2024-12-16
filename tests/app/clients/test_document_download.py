import pytest
import requests
import requests_mock

from app.clients.document_download import DocumentDownloadClient, DocumentDownloadError


@pytest.fixture(scope="function")
def document_download(client, mocker):
    client = DocumentDownloadClient()
    current_app = mocker.Mock(
        config={
            "DOCUMENT_DOWNLOAD_API_HOST": "https://document-download",
            "DOCUMENT_DOWNLOAD_API_KEY": "test-key",
        }
    )
    client.init_app(current_app)
    return client


def test_get_upload_url(document_download):
    assert document_download.get_upload_url("service-id") == "https://document-download/services/service-id/documents"


def test_upload_document(document_download):
    with requests_mock.Mocker() as request_mock:
        request_mock.post(
            "https://document-download/services/service-id/documents",
            json={"document": {"url": "https://document-download/services/service-id/documents/uploaded-url"}},
            request_headers={
                "Authorization": "Bearer test-key",
            },
            status_code=201,
        )

        resp = document_download.upload_document("service-id", {"file": "abababab", "sending_method": "attach"})

    assert resp == {"document": {"url": "https://document-download/services/service-id/documents/uploaded-url"}}


def test_upload_document_with_filename_arg_passed(document_download):
    def match_request(request):
        return b'name="filename"\r\n\r\nfile.pdf' in request.body

    with requests_mock.Mocker() as request_mock:
        request_mock.post(
            "https://document-download/services/service-id/documents",
            json={"document": {"url": "https://document-download/services/service-id/documents/uploaded-url"}},
            request_headers={
                "Authorization": "Bearer test-key",
            },
            status_code=201,
            additional_matcher=match_request,
        )
        response = document_download.upload_document(
            "service-id",
            {"file": "abababab", "filename": "file.pdf", "sending_method": "attach"},
        )

    assert response == {"document": {"url": "https://document-download/services/service-id/documents/uploaded-url"}}


def test_upload_document_without_filename(document_download):
    def match_request(request):
        # filename field is not passed
        return b'name="filename"' not in request.body

    with requests_mock.Mocker() as request_mock:
        request_mock.post(
            "https://document-download/services/service-id/documents",
            json={"document": {"url": "https://document-download/services/service-id/documents/uploaded-url"}},
            request_headers={"Authorization": "Bearer test-key"},
            status_code=201,
            additional_matcher=match_request,
        )
        response = document_download.upload_document("service-id", {"file": "abababab", "sending_method": "attach"})

    assert response == {"document": {"url": "https://document-download/services/service-id/documents/uploaded-url"}}


def test_should_raise_for_status(document_download):
    with pytest.raises(DocumentDownloadError) as excinfo, requests_mock.Mocker() as request_mock:
        request_mock.post(
            "https://document-download/services/service-id/documents",
            json={"error": "Invalid encoding"},
            status_code=403,
        )

        document_download.upload_document("service-id", {"file": "abababab", "sending_method": "attach"})

    assert excinfo.value.message == "Invalid encoding"
    assert excinfo.value.status_code == 403


def test_should_raise_for_connection_errors(document_download):
    with pytest.raises(DocumentDownloadError) as excinfo, requests_mock.Mocker() as request_mock:
        request_mock.post(
            "https://document-download/services/service-id/documents",
            exc=requests.exceptions.ConnectTimeout,
        )

        document_download.upload_document("service-id", {"file": "abababab", "sending_method": "attach"})

    assert excinfo.value.message == "error connecting to document download"
    assert excinfo.value.status_code > 399
