import base64
from cryptography.fernet import Fernet, MultiFernet
from urllib.parse import parse_qsl, urlencode
from uuid import uuid4

from twilio.request_validator import RequestValidator


def generate_log_encryption_key() -> str:
    """Generates a new key

    The value generated here can be applied in SSM for the log encrpytion parameter

    Returns:
        str: A new key in string form
    """
    return Fernet.generate_key().decode()


def decrypt_log_event(event: str, keys: str) -> str:
    """Takes a log event and key string and decrypts the event

    Arsg:
        event (str): Encrypted string
        keys (str): Comma-separated string of valid keys
    Returns:
        str: The decrypted event as a string
    """
    key_list = keys.replace(' ', '').split(',')
    mf = MultiFernet([Fernet(key.encode()) for key in key_list])
    return mf.decrypt(event.encode()).decode()


def validate_signature_and_body(token, uri, body, signature):
    rv = RequestValidator(token)

    # Turn the base64 encoded body into a urlencoded string
    decoded = base64.b64decode(body).decode('utf-8')

    # Use parse_qs to turn it into a list of tuples, then make it a dictionary
    params = dict(parse_qsl(decoded, keep_blank_values=True))

    # Compute signature using decoded params and new signature
    new_signature = rv.compute_signature(uri, params)

    # Turn the dictionary into a urlencoded string, then make it a byte string
    encoded = urlencode(params).encode()

    # Turn byte string into a base64 encoded message
    msg = base64.b64encode(encoded).decode('utf-8')

    assert signature == new_signature


def generate_twilio_signature_and_body(
    token: str,
    uri: str,
    params: dict = None,
    account_sid: str = '',
    addons: str = '',
    api_version: str = '2010-04-01',
    body: str = '',
    from_number: str = '+18888888888',
    from_city: str = 'LOS ANGELES',
    from_country: str = 'US',
    from_state: str = 'CA',
    from_zip: str = '12345',
    message_sid: str = '',
    message_service_sid: str = '',
    num_media: str = '0',
    num_segments: str = '1',
    sms_message_sid: str = '',
    sms_sid: str = '',
    sms_status: str = 'received',
    to_number: str = '+12345678901',
    to_city: str = 'PROVIDENCE',
    to_country: str = 'US',
    to_state: str = 'RI',
    to_zip: str = '02901',
):
    """
    For mocking Twilio signature and body
    """
    # This is done rather than test_params.update(params) because dictionary order matters if recreating a live sample
    if not params:
        msg_sid = f'SM{uuid4()}'.replace('-', '')
        params = {
            'AccountSid': account_sid or f'AC{uuid4()}'.replace('-', ''),
            'AddOns': addons or '{"status":"successful","message":null,"code":null,"results":{}}',
            'ApiVersion': api_version,
            'Body': body or f'test body {uuid4()}',
            'From': from_number,
            'FromCity': from_city,
            'FromCountry': from_country,
            'FromState': from_state,
            'FromZip': from_zip,
            'MessageSid': message_sid or msg_sid,
            'MessagingServiceSid': message_service_sid or f'MG{uuid4()}'.replace('-', ''),
            'NumMedia': num_media,
            'NumSegments': num_segments,
            'SmsMessageSid': sms_message_sid or msg_sid,
            'SmsSid': sms_sid or msg_sid,
            'SmsStatus': sms_status,
            'To': to_number,
            'ToCity': to_city,
            'ToCountry': to_country,
            'ToState': to_state,
            'ToZip': to_zip,
        }

    rv = RequestValidator(token)
    # Does not care about param ordering
    signature = rv.compute_signature(uri, params)

    # If order is different from the params it may not yield what you expect
    encoded = urlencode(params).encode()
    msg_body = base64.b64encode(encoded).decode('utf-8')

    return signature, msg_body


if __name__ == '__main__':
    # How to generate a test body and signature
    # To test real events use VEText's token. Ask the Tech Lead or QA. Tokens are not shared with the team.
    token = '12345678'
    rv = RequestValidator(token)

    uri = 'https://staging-api.va.gov/vanotify/twoway/vettext'

    signature, body = generate_twilio_signature_and_body(token, uri)
    print(f'Body: {body}\n, Signature: {signature}')

    ###################################### For Understanding Each Part of the Process ######################################
    # Turn the base64 encoded body into a urlencoded string
    decoded = base64.b64decode(body).decode('utf-8')

    # Use parse_qs to turn it into a list of tuples, then make it a dictionary
    params = dict(parse_qsl(decoded, keep_blank_values=True))
    print(params)

    # Turn the dictionary into a urlencoded string, then make it a byte string
    encoded = urlencode(params).encode()

    # Turn byte string into a base64 encoded message
    msg = base64.b64encode(encoded).decode('utf-8')

    # Compute signature using decoded params and new signature
    new_signature = rv.compute_signature(uri, params)
    print(new_signature)

    validate_signature_and_body(token, uri, body, signature)
