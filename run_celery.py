#!/usr/bin/env python
import newrelic.agent  # See https://bit.ly/2xBVKBH
from aws_xray_sdk.core import patch_all, xray_recorder
from aws_xray_sdk.ext.flask.middleware import XRayMiddleware
from dotenv import load_dotenv
from flask import Flask

from app.aws.xray.context import NotifyContext

patch_all()

newrelic.agent.initialize()  # noqa: E402

# notify_celery is referenced from manifest_delivery_base.yml, and cannot be removed
from app import create_app, notify_celery  # noqa

load_dotenv()

application = Flask("celery")
create_app(application)

xray_recorder.configure(service='Notify', context=NotifyContext())
XRayMiddleware(application, xray_recorder)

application.app_context().push()
