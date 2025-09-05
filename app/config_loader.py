"""Config loader: SSM by default, optional local .env when NOTIFY_CONFIG_LOCAL=1.

Assumes the SecureString parameter value is a newline-delimited set of lines:
    KEY1=VALUE1\n
    KEY2=VALUE2\n
Comments (# ...) and blank lines are ignored. No JSON support.

Order of precedence (highest wins):
    1. Existing process/Lambda env vars
    2. Injected SSM KEY=VALUE entries (missing keys only)

Env vars:
    NOTIFY_SSM_PARAMETER   (default: ENVIRONMENT_VARIABLES) name of SSM parameter
    NOTIFY_CONFIG_LOCAL    If 1: load from local .env-style file instead of SSM
    NOTIFY_LOCAL_ENV_FILE  Path to local file (default: .env) when local mode active
"""

from __future__ import annotations

import os
import logging
from typing import Dict

_LOG = logging.getLogger("notify.config_loader")


def _fetch_ssm(parameter_name: str) -> str | None:
    try:
        import boto3  # type: ignore

        ssm = boto3.client("ssm")
        resp = ssm.get_parameter(Name=parameter_name, WithDecryption=True)
        return resp["Parameter"]["Value"]
    except Exception as e:  # pragma: no cover - defensive path
        _LOG.warning("config_loader SSM get_parameter(%s) failed: %s", parameter_name, e)
        return None


def _parse(raw: str) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if not k:
            continue
        data[k] = v
    return data


def preload_config() -> None:
    # Local mode: read KEY=VALUE lines from a file, inject missing
    try:
        local_flag = int(os.getenv("NOTIFY_CONFIG_LOCAL", "0"))
    except ValueError:
        local_flag = 0
    if local_flag == 1:
        local_file = os.getenv("NOTIFY_LOCAL_ENV_FILE", ".env")
        try:
            with open(local_file, "r", encoding="utf-8") as f:
                raw = f.read()
        except FileNotFoundError:
            _LOG.warning("config_loader local file %s not found (NOTIFY_CONFIG_LOCAL=1)", local_file)
            return
        kv = _parse(raw)
        injected = 0
        for k, v in kv.items():
            if k in os.environ:
                continue
            os.environ[k] = v
            injected += 1
        if injected:
            _LOG.info("config_loader injected %s variables from local file:%s", injected, local_file)
        return

    # SSM mode (default)
    param = os.getenv("NOTIFY_SSM_PARAMETER", "ENVIRONMENT_VARIABLES")
    raw = _fetch_ssm(param)
    if not raw:
        return
    kv = _parse(raw)
    injected = 0
    for k, v in kv.items():
        if k in os.environ:
            continue
        os.environ[k] = v
        injected += 1
    if injected:
        _LOG.info("config_loader injected %s variables from ssm:%s", injected, param)


if __name__ == "__main__":  # Manual debug helper
    preload_config()
    print("Loaded count:", len([k for k in os.environ.keys()]))
    print("NEW_RELIC keys:")
    for k in sorted(k for k in os.environ.keys() if k.startswith("NEW_RELIC_")):
        print(" ", k)
