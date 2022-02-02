from app.encryption import CryptoSigner

signer = CryptoSigner()


def test_should_sign_content(notify_api):
    signer.init_app(notify_api)
    assert signer.sign("this") != "this"


def test_should_verify_content(notify_api):
    signer.init_app(notify_api)
    signed = signer.sign("this")
    assert signer.verify(signed) == "this"


def test_should_sign_json(notify_api):
    signer.init_app(notify_api)
    signed = signer.sign({"this": "that"})
    assert signer.verify(signed) == {"this": "that"}
