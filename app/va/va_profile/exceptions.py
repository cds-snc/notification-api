from app.exceptions import ExceptionWithFailureReason


class VAProfileException(ExceptionWithFailureReason):
    pass


class VAProfileRetryableException(VAProfileException):
    pass


class VAProfileNonRetryableException(VAProfileException):
    pass


class NoContactInfoException(VAProfileNonRetryableException):
    pass
