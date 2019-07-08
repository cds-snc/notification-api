FROM python:3.6-alpine as base
FROM base as builder

ENV PYTHONDONTWRITEBYTECODE 1

RUN apk add --no-cache build-base git gcc musl-dev postgresql-dev g++ make libffi-dev && rm -rf /var/cache/apk/*

# update pip
RUN python -m pip install wheel

RUN mkdir /install
WORKDIR /install

COPY requirements.txt requirements.txt

RUN set -ex && pip3 install -r requirements.txt

FROM base

RUN apk add --no-cache make git && rm -rf /var/cache/apk/*

COPY --from=builder /install /usr/local

# -- Install Application into container:
RUN set -ex && mkdir /app

WORKDIR /app

COPY . /app

RUN make generate-version-file

CMD ["flask", "run", "-p", "6011", "--host=0.0.0.0"]