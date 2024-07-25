FROM python:3.10-alpine@sha256:7edffe5acc6a2c4c009fece2fbdc85f04fde4c8481202473b880ef3f8fbb2939

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