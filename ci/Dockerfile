FROM python:3.6-alpine

RUN apk update && apk add --no-cache ca-certificates && rm -rf /var/cache/apk/*
COPY ./certs/VA-Internal-S2-RCA1-v1.crt /usr/local/share/ca-certificates/VA-Internal-S2-RCA1-v1.crt
RUN update-ca-certificates

ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

ENV PYTHONDONTWRITEBYTECODE 1
RUN apk add --no-cache bash build-base git gcc musl-dev postgresql-dev g++ make libffi-dev libmagic libcurl python3-dev openssl-dev curl-dev && rm -rf /var/cache/apk/*
RUN python -m pip install wheel

RUN adduser -h /app -D vanotify

WORKDIR /app

COPY --chown=vanotify requirements.txt /app/requirements.txt

RUN pip install -r requirements.txt

USER vanotify

COPY --chown=vanotify . /app
RUN make generate-version-file
ENV PORT=6011
ARG GIT_SHA
ENV GIT_SHA ${GIT_SHA}

ENTRYPOINT ["./scripts/save_certificate.sh"]
CMD ["sh", "-c", "gunicorn -c gunicorn_config.py application"]