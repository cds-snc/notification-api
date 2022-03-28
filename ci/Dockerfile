# Python 3.8 is supported until 14 October 2024.
# Alpine Linux 3.15 is supported until 1 November 2023.
FROM python:3.8-alpine3.15

ARG GIT_SHA

ENV PYTHONDONTWRITEBYTECODE 1 \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PORT=6011 \
    GIT_SHA ${GIT_SHA}

COPY ./certs/VA-Internal-S2-RCA1-v1.crt /usr/local/share/ca-certificates/VA-Internal-S2-RCA1-v1.crt
COPY ./certs/VA-Internal-S2-ICA4.crt /usr/local/share/ca-certificates/VA-Internal-S2-ICA4.crt

RUN apk add --no-cache ca-certificates \
  && update-ca-certificates \
  && apk del --no-cache ca-certificates

RUN adduser -h /app -D vanotify
WORKDIR /app

COPY --chown=vanotify requirements.txt .

RUN apk add --no-cache bash build-base postgresql-dev libffi-dev libmagic libcurl python3-dev openssl-dev curl-dev \
  && apk add --no-cache --virtual .build-deps musl-dev rust cargo git \
  && python -m pip install --upgrade pip==22.0.4 \
  && python -m pip install wheel \
  && pip install --no-cache-dir -r requirements.txt \
  # Remove build dependencies.
  && rm requirements.txt \
  && apk del --no-cache .build-deps

# Copy the host's build context directory (notification-api/) to the image's working directory (/app).
COPY --chown=vanotify . .

# Generate the version file, app/version.py.  This overwrites the default file needed file local development.
RUN apk add --no-cache make \
  && make generate-version-file \
  # Remove build dependencies.
  && apk del --no-cache make

USER vanotify

ENTRYPOINT ["./scripts/save_certificate.sh"]
CMD ["sh", "-c", "gunicorn -c gunicorn_config.py application"]
