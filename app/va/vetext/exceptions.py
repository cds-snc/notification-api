class VETextException(Exception):
    pass


class VETextRetryableException(VETextException):
    pass


class VETextNonRetryableException(VETextException):
    pass


class VETextBadRequestException(VETextNonRetryableException):
    def __init__(
        self,
        *args,
        field: str = None,
        message: str = None,
        **kwargs,
    ) -> None:
        self.field = field
        self.message = message
        super().__init__(*args, **kwargs)
