class RetryableException(Exception):
    pass


class NonRetryableException(Exception):
    pass


class AutoRetryException(Exception):
    pass
