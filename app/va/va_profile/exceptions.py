class VAProfileException(Exception):
    pass


class VAProfileIdNotFoundException(VAProfileException):
    failure_reason = 'No VA Profile Id was found'


class VAProfileRetryableException(VAProfileException):
    failure_reason = 'Retryable VAProfile error occurred'


class VAProfileNonRetryableException(VAProfileException):
    failure_reason = 'Non-retryable VAProfile error occurred'


class NoContactInfoException(VAProfileNonRetryableException):
    failure_reason = 'No contact info found from VA Profile'


class VAProfileIDNotFoundException(VAProfileNonRetryableException):
    failure_reason = 'No VA Profile account found'


class ContactPreferencesException(VAProfileNonRetryableException):
    failure_reason = 'VA Profile contact preferences not allowing contact'


class CommunicationItemNotFoundException(VAProfileNonRetryableException):
    failure_reason = 'No communication bio found from VA Profile'
