#!/bin/bash

docker run --rm -v "$PWD:/mnt" koalaman/shellcheck:v0.9.0 -P ./bin/ -x ./scripts/*.sh