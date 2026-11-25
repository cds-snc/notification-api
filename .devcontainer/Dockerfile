FROM mcr.microsoft.com/vscode/devcontainers/python:3.12@sha256:79a80515d78783e761af1db255e92767c4e887a2d56dbeb85e7753da8c12dc16

RUN rm -f /etc/apt/sources.list.d/yarn.list

ARG KUBENS_VERSION="0.9.4"
ARG AWS_CLI_VERSION="2.41.1"
ENV POETRY_VERSION="1.7.1"
ENV POETRY_VENV_PATH="/home/vscode/.venv/workspace"

# Install packages
RUN apt-get update && \
    apt-get -y install --no-install-recommends \
    apt-utils \
    ca-certificates \
    postgresql-client \
    curl \
    dbus-x11 \
    dnsutils \
    emacs \
    eza \
    fd-find \
    fzf \
    git \
    graphviz \
    iproute2 \
    iputils-ping \
    kcachegrind \
    less \
    libsodium-dev \
    lsb-release \
    man-db \
    manpages \
    net-tools \
    openssh-client \
    procps \
    pyprof2calltree \
    ripgrep \
    sudo \
    tealdeer \
    unzip \
    vim \
    ruby-full \
    libgtk2.0-0 \
    libgtk-3-0 \
    libgbm-dev \
    libnotify-dev \
    libnss3 \
    libxss1 \
    libasound2 \
    libxtst6 \
    xauth \
    xvfb \
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

RUN case "$(dpkg --print-architecture)" in \
            amd64) AWS_CLI_ARCH="x86_64"; AWS_CLI_SHA256="f1b67518c009e9deb94152aaba5cc015e80af6b0630a7931d3662df42b5f568e" ;; \
            arm64) AWS_CLI_ARCH="aarch64"; AWS_CLI_SHA256="83f3bb8440cf6a05e6289f8024126b8c8e15e9513adfe0d6c059747350cdb1e2" ;; \
            *) echo "Unsupported architecture for AWS CLI v2"; exit 1 ;; \
        esac && \
        curl --fail --location --silent --show-error \
            "https://awscli.amazonaws.com/awscli-exe-linux-${AWS_CLI_ARCH}-${AWS_CLI_VERSION}.zip" \
            -o /tmp/awscliv2.zip && \
        echo "${AWS_CLI_SHA256}  /tmp/awscliv2.zip" | sha256sum --check --status && \
        unzip -q /tmp/awscliv2.zip -d /tmp && \
        /tmp/aws/install --update && \
        rm -rf /tmp/aws /tmp/awscliv2.zip

RUN install -d -o vscode -g vscode /home/vscode/.aws/sso/cache

# Upgrade pip
RUN pip install --upgrade pip

# Install kubens
RUN git clone -b v${KUBENS_VERSION} --single-branch https://github.com/ahmetb/kubectx /opt/kubectx \
    && ln -s /opt/kubectx/kubectx /usr/local/bin/kubectx \
    && ln -s /opt/kubectx/kubens /usr/local/bin/kubens

COPY .devcontainer/scripts/notify-dev-entrypoint.sh /usr/local/bin/

ENV SHELL /bin/zsh

EXPOSE 8000
EXPOSE 6011
