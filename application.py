#!/usr/bin/env python
from __future__ import print_function

import os

from apig_wsgi import make_lambda_handler
from app.aws.xray.context import NotifyContext
from aws_xray_sdk.core import patch_all, xray_recorder
from aws_xray_sdk.ext.flask.middleware import XRayMiddleware
from dotenv import load_dotenv
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app

# Patch all supported libraries for X-Ray
# Used to trace requests and responses through the stack
patch_all()

load_dotenv()

application = Flask("api")
application.wsgi_app = ProxyFix(application.wsgi_app)  # type: ignore

app = create_app(application)

xray_recorder.configure(service="Notify-API", context=NotifyContext())
XRayMiddleware(app, xray_recorder)

# New Relic APM for AWS Lambda Only
if os.environ.get("AWS_LAMBDA_RUNTIME_API"):
    import newrelic.agent  # See https://bit.ly/2xBVKBH

    monitored_newrelic_keys = [
        "NEW_RELIC_APP_NAME",
        "NEW_RELIC_ENABLED",
        "NEW_RELIC_DISTRIBUTED_TRACING_ENABLED",
        "NEW_RELIC_ENVIRONMENT",
        "NEW_RELIC_EXTENSION_LOGS_ENABLED",
        "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS",
        "NEW_RELIC_LAMBDA_EXTENSION_ENABLED",
        "NEW_RELIC_LAMBDA_HANDLER",
        "NEW_RELIC_SERVERLESS_MODE_ENABLED",
        "NEW_RELIC_CONFIG_FILE",
    ]

    print("Enabling Lambda API New Relic APM Instrumentation")
    print("New Relic environment variable summary:")

    for key in monitored_newrelic_keys:
        value = os.environ.get(key)
        if value in (None, ""):
            print(f"  {key}=<unset>")
        else:
            print(f"  {key}={value}")

    # https://docs.newrelic.com/docs/apm/agents/python-agent/python-agent-api/wsgiapplication-python-agent-api/
    app.wsgi_app = newrelic.agent.WSGIApplicationWrapper(app.wsgi_app, name="Lambda API")
    newrelic.agent.initialize(environment=app.config["NOTIFY_ENVIRONMENT"])  # noqa: E402
    newrelic.agent.register_application(timeout=20.0)

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
    # Simple handler - New Relic already initialized at module level
    return apig_wsgi_handler(event, context)
