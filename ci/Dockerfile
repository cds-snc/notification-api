FROM python:3.6-alpine

ENV PYTHONDONTWRITEBYTECODE 1
RUN apk add --no-cache bash build-base git gcc musl-dev postgresql-dev g++ make libffi-dev libmagic && rm -rf /var/cache/apk/*
RUN python -m pip install wheel
RUN set -ex && mkdir /app

COPY requirements.txt /app/requirements.txt
WORKDIR /app
RUN pip install -r requirements.txt

COPY . /app
RUN make generate-version-file
ENV PORT=6011
ARG GIT_SHA
ENV GIT_SHA ${GIT_SHA}
CMD ["sh", "-c", "gunicorn -c gunicorn_config.py application"]