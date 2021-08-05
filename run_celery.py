#!/usr/bin/env python
import newrelic.agent  # See https://bit.ly/2xBVKBH
from dotenv import load_dotenv
from flask import Flask

newrelic.agent.initialize()  # noqa: E402

# notify_celery is referenced from manifest_delivery_base.yml, and cannot be removed
from app import create_app, notify_celery  # noqa

load_dotenv()

application = Flask("celery")
create_app(application)
application.app_context().push()
