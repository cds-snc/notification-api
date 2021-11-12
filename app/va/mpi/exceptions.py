class MpiException(Exception):
    pass


class MpiRetryableException(MpiException):
    failure_reason = 'Retryable MPI error occurred'


class MpiNonRetryableException(MpiException):
    failure_reason = 'Non-retryable MPI error occurred'


class IncorrectNumberOfIdentifiersException(MpiNonRetryableException):
    failure_reason = 'Incorrect number of identifiers associated with notification'


class IdentifierNotFound(MpiNonRetryableException):
    failure_reason = 'Requested identifier not found in MPI correlation database'


class MultipleActiveVaProfileIdsException(MpiNonRetryableException):
    failure_reason = 'Multiple active VA Profile ids found in MPI correlation database'


class BeneficiaryDeceasedException(MpiNonRetryableException):
    failure_reason = 'Beneficiary has deceased status in MPI'


class NoSuchIdentifierException(MpiNonRetryableException):
    failure_reason = 'Mpi Profile not found for this identifier'
