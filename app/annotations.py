from functools import wraps

from inspect import signature


def sign_param(func):
    """
    A decorator that signs parameters annotated with `PendingNotification` or `VerifiedNotification`
    before passing them to the decorated function.
    This decorator inspects the function's signature to find parameters annotated with
    `PendingNotification` or `VerifiedNotification`. It then uses `signer_notification.sign`
    to sign these parameters and replaces the original values with the signed values before
    calling the decorated function.
    Args:
        func (Callable): The function to be decorated.
    Returns:
        Callable: The wrapped function with signed parameters.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        from app import signer_notification
        from app.queue import QueueMessage

        sig = signature(func)

        # Find the parameter annotated with VerifyAndSign
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()

        for param_name, param in sig.parameters.items():
            if issubclass(param.annotation, QueueMessage):
                unsigned: QueueMessage = bound_args.arguments[param_name]  # type: ignore
                signed_param = signer_notification.sign(unsigned.to_dict())
                # Replace the signed value with the verified value
                bound_args.arguments[param_name] = signed_param

        # Call the decorated function with the signed value
        result = func(*bound_args.args, **bound_args.kwargs)
        return result

    return wrapper


def unsign_params(func):
    """
    A decorator that verifies the SignedNotification|SignedNotifications typed
    arguments of the decorated function using `CryptoSigner().verify`.
    Args:
        func (callable): The function to be decorated.
    Returns:
        callable: The wrapped function with verification, un-signing decorated
        parameters typed with SignedNotification[s].
    The decorated function should expect the first argument to be a signed string.
    The decorator will verify this signed string before calling the decorated function.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        from app import signer_notification
        from app.types import SignedNotification, SignedNotifications

        sig = signature(func)

        # Find the parameter annotated with VerifyAndSign
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()

        for param_name, param in sig.parameters.items():
            if param.annotation in (SignedNotification, SignedNotifications):
                signed = bound_args.arguments[param_name]

                # Verify the signed string or list of signed strings
                if param.annotation is SignedNotification:
                    verified_value = signer_notification.verify(signed)
                elif param.annotation is SignedNotifications:
                    verified_value = [signer_notification.verify(item) for item in signed]

                # Replace the signed value with the verified value
                bound_args.arguments[param_name] = verified_value

        # Call the decorated function with the verified value
        result = func(*bound_args.args, **bound_args.kwargs)
        return result

    return wrapper


def sign_return(func):
    """
    A decorator that signs the result of the decorated function using CryptoSigner.
    Args:
        func (callable): The function to be decorated.
    Returns:
        callable: The wrapped function that returns a signed result.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        from app import signer_notification

        # Call the decorated function with the verified value
        result = func(*args, **kwargs)

        if isinstance(result, str):
            # Sign the str result of the decorated function
            signed_result = signer_notification.sign(result)
        elif isinstance(result, list):
            # Sign the list result of the decorated function
            signed_result = [signer_notification.sign(item) for item in result]
        else:
            signed_result = result

        return signed_result

    return wrapper
