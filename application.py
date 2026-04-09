#!/usr/bin/env python
from __future__ import print_function

import os

from apig_wsgi import make_lambda_handler
from dotenv import load_dotenv
from environs import Env
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app

load_dotenv()

env = Env()

ff_enable_otel = env.bool("FF_ENABLE_OTEL", default=False)

if not ff_enable_otel:
    from aws_xray_sdk.core import patch_all, xray_recorder
    from aws_xray_sdk.ext.flask.middleware import XRayMiddleware

    from app.aws.xray.context import NotifyContext

    # Patch all supported libraries for X-Ray
    # Used to trace requests and responses through the stack
    patch_all()

is_lambda = os.environ.get("AWS_LAMBDA_RUNTIME_API") is not None
print("is_lambda =", is_lambda)

application = Flask("api")
application.wsgi_app = ProxyFix(application.wsgi_app)  # type: ignore

app = create_app(application)

if not ff_enable_otel:
    # Configure X-Ray after app creation
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
