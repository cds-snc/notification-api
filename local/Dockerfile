FROM python:3.10-alpine@sha256:3a668bb2be7a49c999d97b2fd08eb2e153725125d80692f9ac27a338b939df4a

ENV PYTHONDONTWRITEBYTECODE 1
ENV POETRY_VERSION "1.7.1"

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