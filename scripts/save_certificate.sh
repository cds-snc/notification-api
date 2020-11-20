#! /usr/bin/env sh
set -e

echo "Writing SSL certificate and key to files"

echo $VANOTIFY_SSL_CERT > /app/certs/vanotify_ssl.cert
echo $VANOTIFY_SSL_KEY > /app/certs/vanotify_ssl.key

exec "$@"