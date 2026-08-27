import requests
from flask import current_app


class DocumentDownloadError(Exception):
    def __init__(self, message, status_code):
        self.message = message
        self.status_code = status_code

    @classmethod
    def from_exception(cls, e):
        try:
            message = e.response.json()["error"]
            status_code = e.response.status_code
        except (TypeError, ValueError, AttributeError, KeyError):
            message = "error connecting to document download"
            status_code = e.response.status_code if e.response else 503

        return cls(message, status_code)


class DocumentDownloadClient:
    def init_app(self, app):
        self.api_host = app.config["DOCUMENT_DOWNLOAD_API_HOST"]
        self.auth_token = app.config["DOCUMENT_DOWNLOAD_API_KEY"]

    def get_upload_url(self, service_id):
        return "{}/services/{}/documents".format(self.api_host, service_id)

    def upload_document(self, service_id, personalisation_key):
        try:
            response = requests.post(
                self.get_upload_url(service_id),
                headers={
                    "Authorization": "Bearer {}".format(self.auth_token),
                },
                data={
                    "filename": personalisation_key.get("filename"),
                    "sending_method": personalisation_key["sending_method"],
                },
                files={
                    "document": personalisation_key["file"],
                },
            )

            response.raise_for_status()
        except requests.RequestException as e:
            error = DocumentDownloadError.from_exception(e)
            current_app.logger.warning("Document download request failed with error: {}".format(error.message))

            raise error
        return response.json()

    def delete_document(self, service_id, document_id, sending_method):
        try:
            url = f"{self.api_host}/services/{service_id}/documents/{document_id}"
            response = requests.delete(
                url,
                headers={
                    "Authorization": f"Bearer {self.auth_token}",
                },
                params={
                    "sending_method": sending_method,
                },
            )
            response.raise_for_status()
        except requests.RequestException as e:
            error = DocumentDownloadError.from_exception(e)
            current_app.logger.warning(f"Document delete request failed with error: {error.message}")
            raise error

    def download_document(self, service_id, document_id):
        try:
            url = f"{self.api_host}/services/{service_id}/documents/{document_id}"
            response = requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {self.auth_token}",
                },
                params={
                    "sending_method": "template_attach",
                },
            )
            response.raise_for_status()
        except requests.RequestException as e:
            error = DocumentDownloadError.from_exception(e)
            current_app.logger.warning(f"Document download request failed with error: {error.message}")
            raise error
        return response

    def upload_template_attachment(self, service_id, file_data, filename, mime_type):
        """Upload a template file attachment. Returns the document download api response including the document_id"""
        try:
            response = requests.post(
                self.get_upload_url(service_id),
                headers={
                    "Authorization": "Bearer {}".format(self.auth_token),
                },
                data={
                    "filename": filename,
                    "sending_method": "template_attach",
                },
                files={
                    "document": (filename, file_data, mime_type),
                },
            )
            response.raise_for_status()
        except requests.RequestException as e:
            error = DocumentDownloadError.from_exception(e)
            current_app.logger.warning("Document download request failed with error: {}".format(error.message))
            raise error
        return response.json()

    def check_scan_verdict(self, service_id, document_id, sending_method):
        url = f"{self.api_host}/services/{service_id}/documents/{document_id}/scan-verdict"
        response = requests.post(
            url,
            headers={
                "Authorization": "Bearer {}".format(self.auth_token),
            },
            data={
                "sending_method": sending_method,
            },
        )
        return response
