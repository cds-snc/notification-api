"""
Script to resign certain database fields:
 - api key secrets
 - inbound sms content
 - service callback bearer_tokens

Needs Notify config variables and access to the database. In AWS run on an api pod.

Usage:
    python resign_database.py
    (run from the scripts/ folder)
"""

from dotenv import load_dotenv
from flask import Flask

import sys
sys.path.append('..')  # needed so we can find app (as run from scripts/ folder)

from app import create_app  # noqa: E402
from app.dao.api_key_dao import resign_api_keys  # noqa: E402
from app.dao.inbound_sms_dao import resign_inbound_sms  # noqa: E402
from app.dao.service_callback_api_dao import resign_service_callbacks  # noqa: E402


def resign_all():
    resign_api_keys()
    resign_inbound_sms()
    resign_service_callbacks()


if __name__ == "__main__":
    load_dotenv()
    application = Flask("resign_database")
    create_app(application)
    application.app_context().push()
    resign_all()
