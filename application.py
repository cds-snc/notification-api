#!/usr/bin/env python
from __future__ import print_function

import os

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

is_lambda = os.environ.get("AWS_LAMBDA_RUNTIME_API") is not None
enable_newrelic = os.getenv("ENABLE_NEW_RELIC", "False").lower() == "true"

print("is_lambda =", is_lambda)
print("enable_newrelic =", enable_newrelic)

if is_lambda and enable_newrelic:
    import newrelic.agent

    # Initialize New Relic early, before creating the Flask app
    print("Lambda detected, and New Relic enabled - initializing New Relic agent")
    environment = os.getenv("NOTIFY_ENVIRONMENT", "dev")
    newrelic.agent.initialize("newrelic.ini", environment=environment)

application = Flask("api")
application.wsgi_app = ProxyFix(application.wsgi_app)  # type: ignore

app = create_app(application)

# Configure X-Ray after app creation
xray_recorder.configure(service="Notify-API", context=NotifyContext())
XRayMiddleware(app, xray_recorder)

# It's annoying that we have to do this here, but order matters - so we need to check if is lambda twice.
if is_lambda and enable_newrelic:
    # Wrap the Flask app with New Relic's WSGI wrapper
    app = newrelic.agent.WSGIApplicationWrapper(app)

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
