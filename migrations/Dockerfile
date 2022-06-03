FROM python:3.8-alpine3.15

ENV PYTHONDONTWRITEBYTECODE 1

RUN apk add --no-cache bash build-base git gcc musl-dev postgresql-dev g++ make libffi-dev libmagic libcurl python3-dev openssl-dev curl-dev && rm -rf /var/cache/apk/*
RUN python -m pip install wheel

RUN set -ex && mkdir /app

WORKDIR /app

COPY . /app

RUN set -ex && pip3 install -r requirements.txt
RUN make generate-version-file
CMD ["sh", "-c", "flask db upgrade"]