class VAProfileException(Exception):
    pass


class VAProfileRetryableException(VAProfileException):
    pass


class VAProfileNonRetryableException(VAProfileException):
    pass


class NoContactInfoException(VAProfileNonRetryableException):
    pass
