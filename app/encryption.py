from flask_bcrypt import check_password_hash, generate_password_hash
from itsdangerous import URLSafeSerializer


class CryptoSigner:
    def init_app(self, app):
        self.serializer = URLSafeSerializer(app.config.get("SECRET_KEY"))
        self.salt = app.config.get("DANGEROUS_SALT")

    def sign(self, to_sign):
        return self.serializer.dumps(to_sign, salt=self.salt)

    def verify(self, to_verify):
        return self.serializer.loads(to_verify, salt=self.salt)


def hashpw(password):
    return generate_password_hash(password.encode("UTF-8"), 10).decode("utf-8")


def check_hash(password, hashed_password):
    # If salt is invalid throws a 500 should add try/catch here
    return check_password_hash(hashed_password, password)
