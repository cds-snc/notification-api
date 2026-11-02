#!/bin/bash

docker run --rm -v "$PWD:/mnt" koalaman/shellcheck:v0.11.0@sha256:61862eba1fcf09a484ebcc6feea46f1782532571a34ed51fedf90dd25f925a8d -P ./bin/ -x ./scripts/*.sh