FROM python:3.10-alpine@sha256:1eba91607a236342119c5e2caaab14dc906c8370fe647477279e76d01c6dd733

ENV PYTHONDONTWRITEBYTECODE 1
ENV POETRY_VERSION "1.3.2"

RUN apk add --no-cache bash build-base git gcc musl-dev postgresql-dev g++ make libffi-dev libmagic libcurl curl-dev && rm -rf /var/cache/apk/*

# update pip
RUN python -m pip install wheel poetry==${POETRY_VERSION}

RUN set -ex && mkdir /app

WORKDIR /app

COPY . /app

RUN poetry install

ENV PORT=6011

ARG GIT_SHA
ENV GIT_SHA ${GIT_SHA}

CMD ["sh", "-c", "poetry run gunicorn -c gunicorn_config.py application"]