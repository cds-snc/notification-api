# Python 3.10 is supported until October 2026.
# Alpine Linux 3.19 is supported until 1 November 2025
FROM python:3.10-alpine3.19

ARG GIT_SHA

# REQUESTS_CA_BUNDLE is for the "requests" Python package.
#   https://requests.readthedocs.io/en/latest/user/advanced/#ssl-cert-verification
ENV PYTHONDONTWRITEBYTECODE=1 \
  REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
  PORT=6011 \
  GIT_SHA=${GIT_SHA}

# Transfer DigiCert certificates to the image.
COPY ./certs/* /usr/local/share/ca-certificates/

RUN apk add --no-cache ca-certificates \
  && update-ca-certificates \
  && apk del --no-cache ca-certificates

RUN apk add --no-cache bash build-base git postgresql-dev g++ make libffi-dev libmagic libcurl python3-dev openssl-dev curl-dev wget

RUN adduser -h /app -D vanotify

WORKDIR /app

COPY --chown=vanotify requirements.txt .

RUN apk add --no-cache --virtual .build-deps gcc musl-dev rust cargo \
  && python -m pip install --upgrade pip \
  && python -m pip install wheel \
  # TODO #1375 Temporary add due to errors related to PyYAML and AttributeError.
  && pip install "Cython<3.0" \
  && pip install "pyyaml==6.0.0" --no-build-isolation \
  && pip install --upgrade setuptools==65.5.1 \
  && pip install --no-cache-dir -r requirements.txt \
  # Remove build dependencies.
  && apk del --no-cache .build-deps

# Copy the host's build context directory (notification-api/) to the image's working directory (/app).
COPY --chown=vanotify . .

# Transfer VA certificates to the image.  These certificates are grabbed from a public VA HTTP server.
RUN bash scripts/import-va-certs.sh \
  && apk del --no-cache wget

# Generate the version file, app/version.py.  This overwrites the default file needed for local development.
# The safe.directory modification eliminates the error, "fatal: detected dubious ownership in repository at '/app'".
RUN apk add --no-cache make \
  && git config --global --add safe.directory /app \
  && make generate-version-file \
  && apk del --no-cache make wget

USER vanotify

ENV PORT=6011
ARG GIT_SHA
ENV GIT_SHA ${GIT_SHA}

ENTRYPOINT ["./scripts/save_certificate.sh"]
CMD ["sh", "-c", "ddtrace-run gunicorn -c gunicorn_config.py application"]
