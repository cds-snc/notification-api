#!/bin/bash

aws lambda get-layer-version-by-arn \
--region ca-central-1 \
--arn arn:aws:lambda:ca-central-1:451483290750:layer:NewRelicPython310:39 \
| jq -r '.Content.Location' \
| xargs curl -o ../newrelic-layer.zip