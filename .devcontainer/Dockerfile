FROM python:3.9

ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID
ARG KUBENS_VERSION="0.9.4"
ARG OCTANT_VERSION="0.25.1"

# Install packages
RUN apt-get update \
    && apt-get -y install --no-install-recommends \
        apt-utils \
        postgresql-client \
        2>&1 \
    && apt-get -y install \
        curl \
        emacs \
        exa \
        fd-find \
        git \
        iproute2 \
        less \
        libsodium-dev \
        lsb-release \
        man-db \
        manpages \
        net-tools \
        openssh-client \
        procps \
        sudo \
        tldr \
        unzip \
        vim \
        zsh \
    && groupadd --gid $USER_GID $USERNAME \
    && useradd -s /bin/bash --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME\
    && chmod 0440 /etc/sudoers.d/$USERNAME \
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --upgrade pip

# Install kubens
RUN git clone -b v${KUBENS_VERSION} --single-branch https://github.com/ahmetb/kubectx /opt/kubectx \
    && ln -s /opt/kubectx/kubectx /usr/local/bin/kubectx \
    && ln -s /opt/kubectx/kubens /usr/local/bin/kubens

# Install Octant
RUN curl -Lo octant.tar.gz https://github.com/vmware-tanzu/octant/releases/download/v${OCTANT_VERSION}/octant_${OCTANT_VERSION}_Linux-64bit.tar.gz \
    && tar -xvf octant.tar.gz \
    && mv octant_${OCTANT_VERSION}_Linux-64bit/octant /usr/local/bin/ \
    && rm -rf octant_${OCTANT_VERSION}_Linux-64bit

# Install fonts
RUN curl -O -J -L https://github.com/ryanoasis/nerd-fonts/releases/download/v2.1.0/FiraMono.zip \
    && unzip FiraMono.zip -d ~/.fonts \
    && rm FiraMono.zip \
    && fc-cache -fv

# Install oh-my-zsh
RUN sh -c "$(curl -fsSL https://raw.github.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"

COPY .devcontainer/scripts/notify-dev-entrypoint.sh /usr/local/bin/

ENV SHELL /bin/zsh

EXPOSE 8000
EXPOSE 6011
