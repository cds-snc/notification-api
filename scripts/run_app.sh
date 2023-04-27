#!/bin/sh

set -e

# https://flask.palletsprojects.com/en/2.2.x/config/?highlight=flask_debug#debug-mode
ddtrace-run flask --debug run -p 6011 --host=0.0.0.0
