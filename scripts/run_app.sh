#!/bin/sh

set -e

# https://flask.palletsprojects.com/en/2.2.x/config/?highlight=flask_debug#debug-mode
flask --debug run -p 6011 --host=0.0.0.0
