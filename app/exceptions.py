class DVLAException(Exception):
    def __init__(self, message):
        self.message = message


class NotificationTechnicalFailureException(Exception):
    pass


class ArchiveValidationError(Exception):
    pass


class MalwarePendingException(Exception):
    pass


class InvalidProviderException(Exception):
    pass
