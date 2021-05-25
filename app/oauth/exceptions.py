from app.errors import InvalidRequest


class OAuthException(Exception):
    status_code = None
    message = None


class IncorrectGithubIdException(Exception):
    pass


class LoginWithPasswordException(InvalidRequest):

    def __init__(self, message, status_code):
        super().__init__(message, status_code)
