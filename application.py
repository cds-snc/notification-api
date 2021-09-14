#!/usr/bin/env python
from __future__ import print_function

import os

import awsgi
import sentry_sdk
from dotenv import load_dotenv
from flask import Flask
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app

load_dotenv()

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_URL", ""),
    integrations=[CeleryIntegration(), FlaskIntegration(), RedisIntegration(), SqlalchemyIntegration()],
    release="notify-api@" + os.environ.get("GIT_SHA", ""),
)

application = Flask("api")
application.wsgi_app = ProxyFix(application.wsgi_app)  # type: ignore
app = create_app(application)
app

if os.environ.get("USE_LOCAL_JINJA_TEMPLATES") == "True":
    print("")
    print("========================================================")
    print("")
    print("WARNING: USING LOCAL JINJA from /jinja_templates FOLDER!")
    print(".env USE_LOCAL_JINJA_TEMPLATES=True")
    print("")
    print("========================================================")
    print("")


def handler(event, context):
    return awsgi.response(app, event, context)
