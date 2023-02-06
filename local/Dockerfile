FROM python:3.10-alpine@sha256:ef5536e8f22c1697807cabe68765567cea4558b4b3f3287e2277b336cf2273a5

ENV PYTHONDONTWRITEBYTECODE 1
ENV POETRY_VERSION "1.3.2"

RUN apk add --no-cache bash build-base git gcc musl-dev postgresql-dev g++ make libffi-dev libmagic libcurl curl-dev && rm -rf /var/cache/apk/*

# update pip
RUN python -m pip install wheel poetry==${POETRY_VERSION}

RUN set -ex && mkdir /app

WORKDIR /app

# COPY requirements.txt /app
# RUN set -ex && pip3 install -r requirements.txt

COPY . /app

RUN poetry install

ENV PORT=6011

ARG GIT_SHA
ENV GIT_SHA ${GIT_SHA}

CMD ["poetry", "run", "gunicorn -c gunicorn_config.py application"]