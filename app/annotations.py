from functools import wraps

# from flask import current_app
from inspect import signature

from app import signer_notification
from app.encryption import SignedNotification, SignedNotifications


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
