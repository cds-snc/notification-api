from app.constants import (
    STATUS_REASON_DECLINED,
    STATUS_REASON_NO_CONTACT,
    STATUS_REASON_NO_ID_FOUND,
    STATUS_REASON_NO_PROFILE,
    STATUS_REASON_RETRYABLE,
)


class VAProfileException(Exception):
    pass


class VAProfileIdNotFoundException(VAProfileException):
    failure_reason = 'No VA Profile Id was found'
    status_reason = STATUS_REASON_NO_ID_FOUND


class VAProfileRetryableException(VAProfileException):
    failure_reason = 'Retryable VAProfile error occurred'
    status_reason = STATUS_REASON_RETRYABLE


class VAProfileNonRetryableException(VAProfileException):
    failure_reason = 'Non-retryable VAProfile error occurred'
    status_reason = STATUS_REASON_NO_PROFILE


class NoContactInfoException(VAProfileNonRetryableException):
    failure_reason = 'No contact info found from VA Profile'
    status_reason = STATUS_REASON_NO_CONTACT


class InvalidPhoneNumberException(VAProfileNonRetryableException):
    failure_reason = 'Phone number is invalid'
    status_reason = STATUS_REASON_NO_CONTACT


class VAProfileIDNotFoundException(VAProfileNonRetryableException):
    failure_reason = 'No VA Profile account found'
    status_reason = STATUS_REASON_NO_PROFILE


class ContactPreferencesException(VAProfileNonRetryableException):
    failure_reason = 'VA Profile contact preferences not allowing contact'
    status_reason = STATUS_REASON_DECLINED


class CommunicationItemNotFoundException(VAProfileNonRetryableException):
    failure_reason = 'No communication bio found from VA Profile'
    status_reason = STATUS_REASON_DECLINED
