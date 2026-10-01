FROM mcr.microsoft.com/vscode/devcontainers/python:3.12-bookworm

RUN rm -f /etc/apt/sources.list.d/yarn.list

ARG KUBENS_VERSION="0.9.4"
ENV POETRY_VERSION="1.7.1"
ENV POETRY_VENV_PATH="/home/vscode/.venv/workspace"

# Install packages
RUN apt-get update && \
    apt-get -y install --no-install-recommends \
    apt-utils \
    postgresql-client \
    curl \
    dbus-x11 \
    dnsutils \
    emacs \
    exa \
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
    nodejs \
    npm \
    openssh-client \
    procps \
    pyprof2calltree \
    ripgrep \
    sudo \
    tldr \
    unzip \
    vim \
    ruby-full \
    libgtk2.0-0 \
    libgtk-3-0 \
    libgbm-dev \
    libnotify-dev \
    libgconf-2-4 \
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
            amd64) AWS_CLI_ARCH="x86_64" ;; \
            arm64) AWS_CLI_ARCH="aarch64" ;; \
            *) echo "Unsupported architecture for AWS CLI v2"; exit 1 ;; \
        esac && \
        curl "https://awscli.amazonaws.com/awscli-exe-linux-${AWS_CLI_ARCH}.zip" -o /tmp/awscliv2.zip && \
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
