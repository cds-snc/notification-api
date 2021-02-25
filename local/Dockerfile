FROM python:3.9-alpine

ENV PYTHONDONTWRITEBYTECODE 1

RUN apk add --no-cache bash build-base git gcc musl-dev postgresql-dev g++ make libffi-dev libmagic libcurl curl-dev && rm -rf /var/cache/apk/*

# update pip
RUN python -m pip install wheel

RUN set -ex && mkdir /app

WORKDIR /app

COPY requirements.txt /app
RUN set -ex && pip3 install -r requirements.txt

COPY . /app

ENV PORT=6011

ARG GIT_SHA
ENV GIT_SHA ${GIT_SHA}

CMD ["sh", "-c", "gunicorn -c gunicorn_config.py application"]