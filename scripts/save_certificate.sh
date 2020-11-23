#! /usr/bin/env sh
set -e

echo "Writing SSL certificate and key to files"

export VANOTIFY_SSL_CERT_PATH="/app/certs/vanotify_ssl.cert"
export VANOTIFY_SSL_KEY_PATH="/app/certs/vanotify_ssl.key"

echo $VANOTIFY_SSL_CERT > $VANOTIFY_SSL_CERT_PATH
echo $VANOTIFY_SSL_KEY > $VANOTIFY_SSL_KEY_PATH

exec "$@"