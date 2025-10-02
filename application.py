#!/usr/bin/env python
from __future__ import print_function

import os

import newrelic.agent  # See https://bit.ly/2xBVKBH
from apig_wsgi import make_lambda_handler
from aws_xray_sdk.core import patch_all, xray_recorder
from aws_xray_sdk.ext.flask.middleware import XRayMiddleware
from dotenv import load_dotenv
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app
from app.aws.xray.context import NotifyContext

# Patch all supported libraries for X-Ray
# Used to trace requests and responses through the stack
patch_all()

load_dotenv()

application = Flask("api")
application.wsgi_app = ProxyFix(application.wsgi_app)  # type: ignore

app = create_app(application)

xray_recorder.configure(service="Notify-API", context=NotifyContext())
XRayMiddleware(app, xray_recorder)

apig_wsgi_handler = make_lambda_handler(
    app, binary_support=True, non_binary_content_type_prefixes=["application/yaml", "application/json"]
)

# Initialize New Relic at module load (cold start), not per invocation
# This works for both Lambda (with wrapper) and K8s/ECS (via gunicorn_config.py)
# For Lambda: wrapper handles instrumentation, this adds environment context
# For K8s/ECS: gunicorn_config.py reinitializes with proper settings
# Setting app_name for APM visibility (uses NEW_RELIC_APP_NAME env var)
newrelic.agent.initialize(
    environment=app.config["NOTIFY_ENVIRONMENT"],
    app_name=os.environ.get("NEW_RELIC_APP_NAME")
)  # noqa: E402
newrelic.agent.register_application(timeout=20.0)

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
    # Simple handler - New Relic already initialized at module level
    return apig_wsgi_handler(event, context)
