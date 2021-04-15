class MpiException(Exception):
    pass


class MpiRetryableException(MpiException):
    failure_reason = 'Retryable MPI error occurred'


class MpiNonRetryableException(MpiException):
    failure_reason = 'Non-retryable MPI error occurred'


class IncorrectNumberOfIdentifiersException(MpiNonRetryableException):
    failure_reason = 'Incorrect number of identifiers when getting VA Profile id from MPI'


class IdentifierNotFound(MpiNonRetryableException):
    failure_reason = 'Identifier not found when getting VA Profile id from MPI'


class MultipleActiveVaProfileIdsException(MpiNonRetryableException):
    failure_reason = 'Multiple active VA Profile ids found from MPI'


class BeneficiaryDeceasedException(MpiException):
    failure_reason = 'Beneficiary found to be deceased after getting VA Profile id from MPI'
