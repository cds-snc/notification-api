import itertools
import json
from typing import Optional

from boto3 import resource
import botocore


import requests
from flask import current_app
from notifications_utils.recipients import allowed_to_send_to
from sqlalchemy.orm.exc import NoResultFound

from app.dao.organisation_dao import dao_get_organisation_by_id
from app.dao.service_data_retention_dao import insert_service_data_retention
from app.models import (
    EMAIL_TYPE,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    MOBILE_TYPE,
    ServiceSafelist,
)
from app.variables import PT_DATA_RETENTION_DAYS


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


def get_gc_organisation_data() -> list[dict]:
    "Returns the dataset from the gc-organisations repo"
    bucket = current_app.config["GC_ORGANISATIONS_BUCKET_NAME"]
    filename = current_app.config["GC_ORGANISATIONS_FILENAME"]
    try:
        s3 = resource("s3")
        key = s3.Object(bucket, filename)
        data_str = key.get()["Body"].read().decode("utf-8")
        org_data = json.loads(data_str)
        return org_data

    except botocore.exceptions.ClientError as exception:
        current_app.logger.error("Unable to download s3 file {}/{}".format(bucket, filename))
        raise exception


def get_organisation_id_from_crm_org_notes(org_notes: str) -> Optional[str]:
    """Returns the notify_organisation_id if one exists for the organisation name
    in the org_notes string
    """
    if ">" not in org_notes:
        return None

    # this is like: "Department of Silly Walks > Unit 2"
    organisation_name = org_notes.split(">")[0].strip()

    gc_org_data = get_gc_organisation_data()

    # create 2 dicts that map english and french org names to the notify organisation_id
    en_dict = {}
    fr_dict = {}
    for item in gc_org_data:
        en_dict[item["name_eng"]] = item["notify_organisation_id"]
        fr_dict[item["name_fra"]] = item["notify_organisation_id"]

    # find the org name in the list
    if organisation_name in en_dict:
        return en_dict[organisation_name]
    if organisation_name in fr_dict:
        return fr_dict[organisation_name]
    return None


def add_pt_data_retention(service_id):
    try:
        insert_service_data_retention(service_id, "email", PT_DATA_RETENTION_DAYS)
        insert_service_data_retention(service_id, "sms", PT_DATA_RETENTION_DAYS)
    except Exception as e:
        current_app.logger.error(f"Error setting data retention for service: {service_id}, Error: {e}")


def get_organisation_by_id(organisation_id):
    try:
        organisation = dao_get_organisation_by_id(organisation_id)
    except NoResultFound:
        current_app.logger.warning(f"Could not find organisation with id {organisation_id}")
        return None
    return organisation
