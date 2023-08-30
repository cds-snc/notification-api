import itertools
import json

from flask import current_app
from notifications_utils.recipients import allowed_to_send_to
import requests

from app.models import (
    EMAIL_TYPE,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    MOBILE_TYPE,
    ServiceSafelist,
)


def get_recipients_from_request(request_json, key, type):
    return [(type, recipient) for recipient in request_json.get(key)]


def get_safelist_objects(service_id, request_json):
    return [
        ServiceSafelist.from_string(service_id, type, recipient)
        for type, recipient in (
            get_recipients_from_request(request_json, "phone_numbers", MOBILE_TYPE)
            + get_recipients_from_request(request_json, "email_addresses", EMAIL_TYPE)
        )
    ]


def service_allowed_to_send_to(recipient, service, key_type, allow_safelisted_recipients=True):
    is_simulated = False
    if recipient in current_app.config["SIMULATED_EMAIL_ADDRESSES"] or recipient in current_app.config["SIMULATED_SMS_NUMBERS"]:
        is_simulated = True

    members = safelisted_members(service, key_type, is_simulated, allow_safelisted_recipients)
    if members is None:
        return True

    return allowed_to_send_to(recipient, members)


def safelisted_members(service, key_type, is_simulated=False, allow_safelisted_recipients=True):
    if key_type == KEY_TYPE_TEST:
        return None

    if key_type == KEY_TYPE_NORMAL and not service.restricted:
        return None

    team_members = itertools.chain.from_iterable([user.mobile_number, user.email_address] for user in service.users)
    safelist_members = []

    if is_simulated:
        safelist_members = itertools.chain.from_iterable(
            [current_app.config["SIMULATED_SMS_NUMBERS"], current_app.config["SIMULATED_EMAIL_ADDRESSES"]]
        )
    else:
        safelist_members = [member.recipient for member in service.safelist if allow_safelisted_recipients]

    if (key_type == KEY_TYPE_NORMAL and service.restricted) or (key_type == KEY_TYPE_TEAM):
        return itertools.chain(team_members, safelist_members)


def get_organisation_id_from_crm_org_notes(org_notes: str):
    if ">" not in org_notes:
        return None
    organisation_name = org_notes.split(">")[0].strip()
    response = requests.get(
        current_app.config["CRM_URL"],
        headers={"Authorization": f"token {current_app.config["github_token"]}"}
    )
    response.raise_for_status()

    account_data = json.loads(response.text)

    # todo: find the org name in the list
    # todo: return the org id
    account_name_data = {
        "en": [item["name_eng"] for item in account_data],
        "fr": [item["name_fra"] for item in account_data],
    }

    return "asdfasdf"