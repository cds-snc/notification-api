#!/usr/bin/env python
import os

from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.ext.flask.middleware import XRayMiddleware
from dotenv import load_dotenv
from flask import Flask

from app.aws.xray.context import NotifyContext

environment = os.environ.get("NOTIFY_ENVIRONMENT")

# notify_celery is referenced from manifest_delivery_base.yml, and cannot be removed
from app import create_app, notify_celery  # noqa

load_dotenv()

application = Flask("celery")
create_app(application)

xray_recorder.configure(service="Notify", context=NotifyContext())
XRayMiddleware(application, xray_recorder)

application.app_context().push()
