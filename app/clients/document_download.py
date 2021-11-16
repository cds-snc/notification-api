class DocumentDownloadError(Exception):
    def __init__(self, message, status_code):
        self.message = message
        self.status_code = status_code

    @classmethod
    def from_exception(cls, e):
        try:
            message = e.response.json()['error']
            status_code = e.response.status_code
        except (TypeError, ValueError, AttributeError, KeyError):
            message = 'connection error'
            status_code = 503

        return cls(message, status_code)


class DocumentDownloadClient:

    def init_app(self, app):
        self.api_host = app.config['DOCUMENT_DOWNLOAD_API_HOST']
        self.auth_token = app.config['DOCUMENT_DOWNLOAD_API_KEY']

    def get_upload_url(self, service_id):
        return "{}/services/{}/documents".format(self.api_host, service_id)
