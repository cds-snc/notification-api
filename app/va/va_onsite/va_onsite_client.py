import json
import jwt
import requests
import time

from app.constants import HTTP_TIMEOUT


class VAOnsiteClient:
    __VA_ONSITE_USER = 'va_notify'

    def init_app(
        self,
        logger,
        url: str,
        va_onsite_secret: str,
    ):
        """Initializes the VAOnsiteClient with appropriate data.

        :param logger: the application logger
        :param url: the url to send the information to in a string format
        :param va_onsite_secret: the secret key in string format used to validate the connection
        """
        self.timeout = HTTP_TIMEOUT
        self.logger = logger
        self.url_base = url
        self.va_onsite_secret = va_onsite_secret

    def post_onsite_notification(
        self,
        data: dict,
    ):
        """Returns the JSON that is retrieved from the `POST` request sent to onsite_notifications

        :param data: The dict onsite_notifications is expecting to see
        """

        self.logger.info('Calling VAOnsiteClient.post_onsite_notification with data: %s', data)
        response = None

        try:
            response = requests.post(
                url=f'{ self.url_base }/v0/onsite_notifications',
                data=json.dumps(data),
                headers=self._build_header(),
                timeout=self.timeout,
            )
        except Exception as e:
            self.logger.exception(e)
        else:
            self.logger.info(
                'onsite_notifications POST response: status_code=%d, json=%s', response.status_code, response.json()
            )

        return response

    def _build_header(self) -> dict:
        """Returns the dict of the header to be sent with the JWT"""
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self._encode_jwt(self.__VA_ONSITE_USER, self.va_onsite_secret)}',
        }

    def _encode_jwt(
        self,
        user: str,
        secret_key: str,
        algo: str = 'ES256',
    ):
        """Returns the JWT encoded using the given algorithm

        :param user: string that will be used for the `user` value in the `data` dict
        :param secret_key: key to use in the authentication section of the JWT
        :param algo: algorithm used to encrypt the JWT
        """
        current_timestamp = int(time.time())
        data = {'user': user, 'iat': current_timestamp, 'exp': current_timestamp + 60}

        return jwt.encode(data, secret_key, algorithm=algo)
