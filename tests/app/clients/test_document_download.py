import pytest

from app.clients.document_download import DocumentDownloadClient


@pytest.fixture(scope='function')
def document_download(client, mocker):
    client = DocumentDownloadClient()
    current_app = mocker.Mock(config={
        'DOCUMENT_DOWNLOAD_API_HOST': 'https://document-download',
        'DOCUMENT_DOWNLOAD_API_KEY': 'test-key'
    })
    client.init_app(current_app)
    return client


def test_get_upload_url(document_download):
    assert document_download.get_upload_url('service-id') == 'https://document-download/services/service-id/documents'
