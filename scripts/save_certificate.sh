#! /usr/bin/env sh
set -e

echo "Writing SSL certificate and key to files"
echo "$VANOTIFY_SSL_CERT" > $VANOTIFY_SSL_CERT_PATH
echo "$VANOTIFY_SSL_KEY" > $VANOTIFY_SSL_KEY_PATH

exec "$@"