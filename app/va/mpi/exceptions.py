from app.constants import (
    STATUS_REASON_DECEASED,
    STATUS_REASON_NO_ID_FOUND,
    STATUS_REASON_NO_PROFILE,
    STATUS_REASON_RETRYABLE,
)


class MpiException(Exception):
    pass


class MpiRetryableException(MpiException):
    failure_reason = 'Retryable MPI error occurred'
    status_reason = STATUS_REASON_RETRYABLE


class MpiNonRetryableException(MpiException):
    failure_reason = 'Non-retryable MPI error occurred'
    status_reason = STATUS_REASON_NO_ID_FOUND


class IncorrectNumberOfIdentifiersException(MpiNonRetryableException):
    failure_reason = 'Incorrect number of identifiers associated with notification'
    status_reason = STATUS_REASON_NO_PROFILE


class IdentifierNotFound(MpiNonRetryableException):
    failure_reason = 'Requested identifier not found in MPI correlation database'
    status_reason = STATUS_REASON_NO_ID_FOUND


class MultipleActiveVaProfileIdsException(MpiNonRetryableException):
    failure_reason = 'Multiple active VA Profile ids found in MPI correlation database'
    status_reason = STATUS_REASON_NO_ID_FOUND


class BeneficiaryDeceasedException(MpiNonRetryableException):
    failure_reason = 'Beneficiary has deceased status in MPI'
    status_reason = STATUS_REASON_DECEASED


class NoSuchIdentifierException(MpiNonRetryableException):
    failure_reason = 'Mpi Profile not found for this identifier'
    status_reason = STATUS_REASON_NO_ID_FOUND
