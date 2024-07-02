# Python 3.10 is supported until October 2026.
# Alpine Linux 3.19 is supported until 1 November 2025
FROM python:3.10-alpine3.19 as builder

# REQUESTS_CA_BUNDLE is for the "requests" Python package.
#   https://requests.readthedocs.io/en/latest/user/advanced/#ssl-cert-verification
ENV PYTHONDONTWRITEBYTECODE=1 \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PORT=6011 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_NO_INTERACTION=1

# Add poetry home location to path
ENV PATH="$POETRY_HOME/bin:$PATH"

# Move repo certs to usr certs
COPY certs/* /usr/local/share/ca-certificates/

# Copy only necessary files for builder
COPY .git Makefile scripts/import-va-certs.sh poetry.lock pyproject.toml /

# Install dependencies
RUN apk add --no-cache bash build-base git postgresql-dev g++ make libffi-dev libmagic libcurl python3-dev openssl-dev \
    curl-dev wget openssl

# Import all VA Certs not in the certs folder and make a version.py file
RUN bash import-va-certs.sh && make generate-version-file

# Arguments for this poetry install
ARG POETRY_ARGS

# Used in the final stage
ARG FLASK_DEBUG=0
ARG TEST_FOLDER="[none-if-not-testing]"

# # RUN apk add --no-cache --virtual .build-deps gcc musl-dev rust cargo curl \
RUN apk add --no-cache --virtual .build-deps cargo curl gcc musl-dev rust \
    && curl -sSL https://install.python-poetry.org | python3 - \
    && poetry install --no-root --no-ansi $POETRY_ARGS

########################################################################################################################

# # Python 3.10 is supported until October 2026.
# # Alpine Linux 3.19 is supported until 1 November 2025
FROM python:3.10-alpine3.19

ARG FLASK_DEBUG
ARG TEST_FOLDER

ENV PYTHONDONTWRITEBYTECODE=1 \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    # https://flask.palletsprojects.com/en/2.2.x/config/?highlight=flask_debug#DEBUG
    FLASK_DEBUG=$FLASK_DEBUG \
    PATH="/.venv/bin:$PATH" \
    PORT=6011

WORKDIR /app

RUN adduser -h /app -D vanotify

# From context and only what is necessary, importing relative to WORKDIR
COPY app/ app
COPY cd/ cd
COPY migrations/ migrations
COPY scripts/ scripts

# Non-relative import since multiple files
COPY gunicorn_config.py application.py Makefile pytest.ini run_celery.py pyproject.toml /app/

# Assign ownership of the certs to vanotify due to save_certificate.sh
COPY --chown=vanotify certs/ certs

# Tests, using glob pattern to avoid copying
COPY $TEST_FOLDER/ tests

# Copy builder files - version must come after context COPY, importing to absolute location
COPY --from=builder /.venv /.venv
COPY --from=builder --chown=vanotify /app/version.py /app/app/version.py
COPY --from=builder --chown=vanotify /usr/local/share/ca-certificates /usr/local/share/ca-certificates/
COPY --from=builder --chown=vanotify /usr/share/ca-certificates /usr/share/ca-certificates/

# Populate /etc/ssl/certs/ with symlinks to /usr/[local/]share/ca-certificates/ certs
RUN apk add --no-cache ca-certificates build-base bash libcurl openssl-dev \
    && update-ca-certificates \
    && apk del --no-cache ca-certificates

USER vanotify

ENTRYPOINT ["./scripts/save_certificate.sh"]
CMD ["sh", "-c", "ddtrace-run gunicorn -c gunicorn_config.py application"]
