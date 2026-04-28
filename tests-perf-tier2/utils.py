from datetime import datetime

from tier2_config import SIMULATED_EMAIL_ADDRESSES, SIMULATED_SMS_NUMBER


def api_headers(api_key: str) -> dict:
    """Build Authorization header from a full API key string."""
    return {"Authorization": f"ApiKey-v1 {api_key[-36:]}"}


def sms_json(template_id: str, ref: str, phone_number: str = SIMULATED_SMS_NUMBER, personalisation: dict | None = None):
    payload = {
        "phone_number": phone_number,
        "template_id": template_id,
        "reference": f"{datetime.utcnow().isoformat()} {ref}",
    }
    if personalisation:
        payload["personalisation"] = personalisation
    return payload


def email_json(
    template_id: str, ref: str, email_address: str = SIMULATED_EMAIL_ADDRESSES[0], personalisation: dict | None = None
):
    payload = {
        "email_address": email_address,
        "template_id": template_id,
        "reference": f"{datetime.utcnow().isoformat()} {ref}",
    }
    if personalisation:
        payload["personalisation"] = personalisation
    return payload
