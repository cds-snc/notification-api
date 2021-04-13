from app.exceptions import ExceptionWithFailureReason


class MpiException(ExceptionWithFailureReason):
    pass


class MpiRetryableException(MpiException):
    pass


class MpiNonRetryableException(MpiException):
    pass


class IncorrectNumberOfIdentifiersException(MpiNonRetryableException):
    pass


class IdentifierNotFound(MpiNonRetryableException):
    pass


class MultipleActiveVaProfileIdsException(MpiNonRetryableException):
    pass


class BeneficiaryDeceasedException(MpiException):
    pass
