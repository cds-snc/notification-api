#!/usr/bin/env python
import newrelic.agent  # See https://bit.ly/2xBVKBH
newrelic.agent.initialize()  # noqa: E402
from flask import Flask

# notify_celery is referenced from manifest_delivery_base.yml, and cannot be removed
from app import notify_celery, create_app  # noqa

from dotenv import load_dotenv

load_dotenv()

application = Flask('delivery')
create_app(application)
application.app_context().push()
