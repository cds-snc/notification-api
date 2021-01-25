FROM python:3.9

ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && apt-get -y install --no-install-recommends apt-utils 2>&1 \
    && apt-get -y install git openssh-client less iproute2 procps lsb-release libsodium-dev \
    && groupadd --gid $USER_GID $USERNAME \
    && useradd -s /bin/bash --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && apt-get install -y sudo \
    && apt-get -y install curl unzip net-tools emacs fd-find exa \
    && apt-get -y install manpages man-db tldr \
    && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME\
    && chmod 0440 /etc/sudoers.d/$USERNAME \
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

RUN curl -O -J -L https://github.com/ryanoasis/nerd-fonts/releases/download/v2.1.0/FiraMono.zip \
    && unzip FiraMono.zip -d ~/.fonts \
    && rm FiraMono.zip \
    && fc-cache -fv

RUN curl -fsSL https://starship.rs/install.sh | bash -s -- -y

COPY .devcontainer/scripts/notify-dev-entrypoint.sh /usr/local/bin/

EXPOSE 8000

RUN python -m pip install wheel

RUN echo "eval '$(starship init bash)'" >> /root/.bashrc
