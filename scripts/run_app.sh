#!/bin/sh

set -e

#flask run -p 6011 --host=0.0.0.0
ddtrace-run flask run -p 6011 --host=0.0.0.0
