#!/bin/bash

# we need the version file to exist otherwise the app will blow up
make generate-version-file

# Install Python development dependencies
pip3 install -r requirements_for_test.txt

# Upgrade databases
flask db upgrade
