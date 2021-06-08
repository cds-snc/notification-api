#!/bin/sh
jmeter -n -t './TestSendNotification.jmx' -o test-output -j test.log -q config.properties