#!/usr/bin/env python
from __future__ import print_function

import os

import newrelic.agent  # See https://bit.ly/2xBVKBH

# import sentry_sdk
from apig_wsgi import make_lambda_handler
from dotenv import load_dotenv
from flask import Flask

# from sentry_sdk.integrations.celery import CeleryIntegration
# from sentry_sdk.integrations.flask import FlaskIntegration
# from sentry_sdk.integrations.redis import RedisIntegration
# from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app

load_dotenv()

# if "SENTRY_URL" in os.environ:
#     sentry_sdk.init(  # type: ignore
#         dsn=os.environ.get("SENTRY_URL", ""),
#         integrations=[CeleryIntegration(), FlaskIntegration(), RedisIntegration(), SqlalchemyIntegration()],
#         release="notify-api@" + os.environ.get("GIT_SHA", ""),
#     )

application = Flask("api")
application.wsgi_app = ProxyFix(application.wsgi_app)  # type: ignore
app = create_app(application)

apig_wsgi_handler = make_lambda_handler(app, binary_support=True)

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
    newrelic.agent.initialize()  # noqa: E402
    newrelic.agent.register_application(timeout=20.0)
    return apig_wsgi_handler(event, context)
