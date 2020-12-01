#! /usr/bin/env sh
set -e

if [ -z "$VANOTIFY_SSL_CERT_PATH" -o -z "$VANOTIFY_SSL_KEY_PATH" ]
then
  echo "bypassing VAProfile cert and key file generation"
else
  echo "Writing SSL certificate and key to files"
  echo "$VANOTIFY_SSL_CERT" > $VANOTIFY_SSL_CERT_PATH
  echo "$VANOTIFY_SSL_KEY" > $VANOTIFY_SSL_KEY_PATH
fi

exec "$@"