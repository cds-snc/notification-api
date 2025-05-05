#!/usr/bin/env python

# In app/scripts/, the shell scripts run_celery.sh and run_celery_beat.sh utilize this file.

from flask import Flask

# notify_celery is referenced from manifest_delivery_base.yml, and cannot be removed
from app import notify_celery, create_app  # noqa

from dotenv import load_dotenv

load_dotenv()

application = Flask('delivery', static_folder=None)
create_app(application)
application.app_context().push()
