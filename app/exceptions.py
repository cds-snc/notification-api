class DVLAException(Exception):
    def __init__(self, message):
        self.message = message


class NotificationTechnicalFailureException(Exception):
    pass


class ArchiveValidationError(Exception):
    pass


class MalwareScanInProgressException(Exception):
    pass


class MalwareDetectedException(Exception):
    pass


class InvalidUrlException(Exception):
    pass


class DocumentDownloadException(Exception):
    pass
