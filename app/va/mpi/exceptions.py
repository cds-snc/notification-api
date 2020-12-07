class MpiException(Exception):
    pass


class MpiRetryableException(MpiException):
    pass


class MpiNonRetryableException(MpiException):
    pass


class UnsupportedIdentifierException(MpiNonRetryableException):
    pass


class IdentifierNotFound(MpiNonRetryableException):
    pass


class IncorrectNumberOfIdentifiersException(MpiNonRetryableException):
    pass
