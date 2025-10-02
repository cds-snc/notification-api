#!/usr/bin/env python
from __future__ import print_function

import os

import newrelic.agent
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

# Initialize New Relic with custom environment parameter
# In Lambda: wrapper calls initialize() first, this adds environment config
# In K8s/ECS: reads from newrelic.ini via gunicorn_config.py
if os.environ.get("NOTIFY_ENVIRONMENT"):
    newrelic.agent.initialize(environment=os.environ["NOTIFY_ENVIRONMENT"])

application = Flask("api")
application.wsgi_app = ProxyFix(application.wsgi_app)  # type: ignore

app = create_app(application)

# Register this application instance with New Relic
# This ensures the agent can properly track this application in both Lambda and K8s/ECS
newrelic.agent.register_application(timeout=20.0)

xray_recorder.configure(service="Notify-API", context=NotifyContext())
XRayMiddleware(app, xray_recorder)

apig_wsgi_handler = make_lambda_handler(
    app, binary_support=True, non_binary_content_type_prefixes=["application/yaml", "application/json"]
)

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
    return apig_wsgi_handler(event, context)
