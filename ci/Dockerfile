# Alpine Linux 3.15 is supported until 1 November 2023.
FROM python:3.8-alpine3.15

ENV PYTHONDONTWRITEBYTECODE 1
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

COPY ./certs/VA-Internal-S2-RCA1-v1.crt /usr/local/share/ca-certificates/VA-Internal-S2-RCA1-v1.crt
COPY ./certs/VA-Internal-S2-ICA4.crt /usr/local/share/ca-certificates/VA-Internal-S2-ICA4.crt

RUN apk add --no-cache ca-certificates \
  && update-ca-certificates \
  && apk del --no-cache ca-certificates

RUN apk add --no-cache bash build-base git postgresql-dev g++ make libffi-dev libmagic libcurl python3-dev openssl-dev curl-dev

RUN adduser -h /app -D vanotify

WORKDIR /app

COPY --chown=vanotify requirements.txt /app/requirements.txt

RUN apk add --no-cache --virtual .build-deps \
    gcc \
    musl-dev \
    rust \
    cargo \
  && python -m pip install --upgrade pip==22.0.4 \
  && python -m pip install wheel \
  && pip install --no-cache-dir -r requirements.txt \
  && apk del --no-cache .build-deps

USER vanotify

COPY --chown=vanotify . /app
RUN make generate-version-file
ENV PORT=6011
ARG GIT_SHA
ENV GIT_SHA ${GIT_SHA}

ENTRYPOINT ["./scripts/save_certificate.sh"]
CMD ["sh", "-c", "gunicorn -c gunicorn_config.py application"]
