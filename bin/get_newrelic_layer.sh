#!/bin/bash

# see https://layers.newrelic-external.com/

aws lambda get-layer-version-by-arn \
--region ca-central-1 \
--arn arn:aws:lambda:ca-central-1:451483290750:layer:NewRelicPython312:22 \
| jq -r '.Content.Location' \
| xargs curl -o ../newrelic-layer.zip
