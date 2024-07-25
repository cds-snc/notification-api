#!/bin/bash

# we need the version file to exist otherwise the app will blow up
make generate-version-file

# Install Python development dependencies
poetry install --only test

# Upgrade databases
flask db upgrade
