FROM python:3.9-alpine3.13

ENV PYTHONDONTWRITEBYTECODE 1

RUN apk add --no-cache bash build-base git libtool cmake autoconf automake gcc musl-dev postgresql-dev g++ libexecinfo-dev make libffi-dev libmagic libcurl curl-dev rust cargo && rm -rf /var/cache/apk/*

# update pip
RUN python -m pip install wheel
RUN python -m pip install --upgrade pip

RUN set -ex && mkdir /app

WORKDIR /app

COPY . /app

RUN set -ex && pip3 install -r requirements_for_test.txt

RUN make generate-version-file

ARG GIT_SHA

ENV GIT_SHA=${GIT_SHA} \ 
    LOAD_TEST_PHONE_NUMBER=16132532222 \ 
    LOAD_TEST_EMAIL=success@simulator.amazonses.com \
    LOAD_TEST_DOMAIN=https://api.staging.notification.cdssandbox.xyz \
    LOAD_TEST_SMS_TEMPLATE_ID=83d01f06-a818-4134-bd69-ce90a2949280 \
    LOAD_TEST_BULK_EMAIL_TEMPLATE_ID=5ebee3b7-63c0-4052-a8cb-387b818df627 \
    LOAD_TEST_EMAIL_TEMPLATE_ID=a59b313d-8de2-4973-ac2f-66de7ec0b239 \
    LOAD_TEST_EMAIL_WITH_ATTACHMENT_TEMPLATE_ID=a59b313d-8de2-4973-ac2f-66de7ec0b239 \
    LOAD_TEST_EMAIL_WITH_LINK_TEMPLATE_ID=5ebee3b7-63c0-4052-a8cb-387b818df627 \
    TEST_AUTH_HEADER="ApiKey-v1 c55039fc-c0e1-44db-a14e-b6a669148ec6"

ENTRYPOINT [ "sh", "-c", "locust --headless --config tests-perf/locust/locust.conf --csv notify-performance-test" ]
