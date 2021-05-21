class OAuthException(Exception):
    status_code = None
    message = None


class IncorrectGithubIdException(Exception):
    pass
