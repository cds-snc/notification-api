# === CI STAGE ===
FROM python:3.10-alpine3.19 AS ci

# Set common environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PORT=6011 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_NO_INTERACTION=1
# Ensure poetry is in PATH
ENV PATH="$POETRY_HOME/bin:$PATH"

# Copy certificates
COPY certs/* /usr/local/share/ca-certificates/

# Copy necessary files for dependency installation and build steps
COPY .git Makefile scripts/import-va-certs.sh poetry.lock pyproject.toml /

# Install system build dependencies and other packages
RUN apk add --no-cache bash build-base git postgresql-dev g++ make libffi-dev libmagic libcurl python3-dev openssl-dev \
    curl-dev wget openssl && \
    # Import extra VA certs and generate a version file
    bash import-va-certs.sh && make generate-version-file

# Arguments for Poetry and runtime settings
ARG POETRY_ARGS
ARG FLASK_DEBUG=0
ARG TEST_FOLDER="[none-if-not-testing]"

# Install build tools, upgrade pip, and install Poetry and dependencies
RUN apk add --no-cache --virtual .build-deps cargo curl gcc musl-dev rust \
    && pip3 install --upgrade pip setuptools \
    && curl -sSL https://install.python-poetry.org | POETRY_VERSION=1.8.4 python3 - \
    && poetry install --no-root --no-ansi $POETRY_ARGS

WORKDIR /app

# Copy full context for CI (tests, lambda_functions, and app)
COPY app/ app
COPY lambda_functions/ lambda_functions
COPY test_csv_files/ test_csv_files
COPY migrations/ migrations
COPY scripts/ scripts
COPY images/ images
COPY gunicorn_config.py application.py Makefile pytest.ini run_celery.py pyproject.toml poetry.lock /app/

ENV PATH="/.venv/bin:$PATH"

# Create and switch to a non-root user
RUN adduser -h /app -D vanotify
USER vanotify

# Default command for CI (e.g. running tests)
ENTRYPOINT ["/bin/sh", "-c"]

# === PRODUCTION STAGE: Slim image for ECS deployment ===
FROM python:3.10-alpine3.19 AS production

ARG FLASK_DEBUG
ENV PYTHONDONTWRITEBYTECODE=1 \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    FLASK_DEBUG=$FLASK_DEBUG \
    PATH="/.venv/bin:$PATH" \
    PORT=6011

WORKDIR /app

# Create non-root user
RUN adduser -h /app -D vanotify

# Copy only production-relevant assets (omitting tests and lambda_functions)
COPY app/ app
COPY cd/ cd
COPY migrations/ migrations
COPY scripts/ scripts
COPY images/ images
COPY gunicorn_config.py application.py Makefile pytest.ini run_celery.py pyproject.toml poetry.lock /app/
COPY --chown=vanotify certs/ certs

# Upgrade pip and setuptools
RUN pip3 install --upgrade pip setuptools

# Copy the built virtual environment and version file from the CI stage
COPY --from=ci /.venv /.venv
COPY --from=ci --chown=vanotify /app/version.py /app/app/version.py
COPY --from=ci --chown=vanotify /usr/local/share/ca-certificates /usr/local/share/ca-certificates/
COPY --from=ci --chown=vanotify /usr/share/ca-certificates /usr/share/ca-certificates/

# Install and update certificates at runtime
RUN apk add --no-cache ca-certificates build-base bash libcurl openssl-dev \
    && update-ca-certificates \
    && apk del --no-cache ca-certificates

USER vanotify

ENTRYPOINT ["./scripts/save_certificate.sh"]
CMD ["sh", "-c", "ddtrace-run gunicorn -c gunicorn_config.py application"]
