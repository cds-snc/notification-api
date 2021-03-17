import requests

__all__ = [
    'BearerAuth'
]


class BearerAuth(requests.auth.AuthBase):
    def __init__(self, token: str):
        self.token = token

    def __call__(self, r: requests.Request):
        r.headers["Authorization"] = "Bearer " + self.token
        return r
