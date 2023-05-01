"""
Script to resign certain database fields:
 - api key secrets
 - inbound sms content
 - service callback bearer_tokens

Needs Notify config variables and access to the database. In AWS run on an api pod.

Usage (run from the scripts/ folder):
    python resign_database.py [unsafe]
    - unsafe: unsign regardless of whether the current secret key can verify the signature
"""

import argparse
import sys

from dotenv import load_dotenv
from flask import Flask

sys.path.append('..')  # needed so we can find app (as run from scripts/ folder)

from app import create_app  # noqa: E402
from app.dao.api_key_dao import resign_api_keys  # noqa: E402
from app.dao.inbound_sms_dao import resign_inbound_sms  # noqa: E402
from app.dao.notifications_dao import resign_notifications  # noqa: E402
from app.dao.service_callback_api_dao import resign_service_callbacks  # noqa: E402


def resign_all(unsafe: bool = False):
    resign_api_keys(unsafe)
    resign_inbound_sms(unsafe)
    resign_service_callbacks(unsafe)
    resign_notifications(unsafe)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--unsafe", default=False, action='store_true', help="resign notifications that have a bad signature")
    args = parser.parse_args()
    
    load_dotenv()
    application = Flask("resign_database")
    create_app(application)
    application.app_context().push()    
    
    resign_all(args.unsafe)
