#!/bin/bash

# we need the version file to exist otherwise the app will blow up
make generate-version-file

# Upgrade databases
flask db upgrade
