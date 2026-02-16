#!/usr/bin/env python
import os

from dotenv import load_dotenv
from environs import Env
from flask import Flask

environment = os.environ.get("NOTIFY_ENVIRONMENT")
env = Env()
ff_enable_otel = env.bool("FF_ENABLE_OTEL", default=False)
enable_newrelic = env.bool("ENABLE_NEW_RELIC", default=False) and not ff_enable_otel

print("enable_newrelic =", enable_newrelic)

if enable_newrelic:
    import newrelic.agent

    newrelic.agent.initialize(environment=environment)  # noqa: E402

# notify_celery is referenced from manifest_delivery_base.yml, and cannot be removed
from app import create_app, notify_celery  # noqa

load_dotenv()

application = Flask("celery")
create_app(application)

if not ff_enable_otel:
    from aws_xray_sdk.core import xray_recorder
    from aws_xray_sdk.ext.flask.middleware import XRayMiddleware

    from app.aws.xray.context import NotifyContext

    xray_recorder.configure(service="Notify", context=NotifyContext())
    XRayMiddleware(application, xray_recorder)

application.app_context().push()
