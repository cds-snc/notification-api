class VAProfileException(Exception):
    pass


class VAProfileRetryableException(VAProfileException):
    failure_reason = 'Retryable VAProfile error occurred'


class VAProfileNonRetryableException(VAProfileException):
    failure_reason = 'Non-retryable VAProfile error occurred'


class NoContactInfoException(VAProfileNonRetryableException):
    failure_reason = 'No contact info found from VA Profile'
