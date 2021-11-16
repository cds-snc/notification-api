class DocumentDownloadClient:

    def init_app(self, app):
        self.api_host = app.config['DOCUMENT_DOWNLOAD_API_HOST']
        self.auth_token = app.config['DOCUMENT_DOWNLOAD_API_KEY']

    def get_upload_url(self, service_id):
        return "{}/services/{}/documents".format(self.api_host, service_id)
