#!/usr/bin/env python
from __future__ import print_function

from flask import Flask

from app import create_app

from dotenv import load_dotenv

load_dotenv()

application = Flask('app')
create_app(application)
