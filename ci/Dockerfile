FROM python:3.6-alpine

ENV PYTHONDONTWRITEBYTECODE 1

RUN apk add --no-cache build-base git gcc musl-dev postgresql-dev g++ make libffi-dev && rm -rf /var/cache/apk/*

# update pip
RUN python -m pip install wheel

RUN set -ex && mkdir /app

WORKDIR /app

COPY . /app

RUN set -ex && pip3 install -r requirements.txt

RUN make generate-version-file

CMD ["flask", "run", "-p", "6011", "--host=0.0.0.0"]