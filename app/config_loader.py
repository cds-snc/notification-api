"""Minimal SSM-only aggregated config loader.

Goal: shrink the configured Lambda environment (circumvent 4KB limit) by
placing the bulk of key/value pairs inside a single SSM SecureString parameter
and loading it at cold start. Only missing keys are injected so any explicitly
configured Lambda variables override the SSM blob.

Usage:
    1. Store a SecureString parameter (default name: ENVIRONMENT_VARIABLES)
         whose value is either JSON ( {"KEY": "VALUE"} ) or classic .env lines.
    2. Set (optionally) NOTIFY_SSM_PARAMETER to override the default name.
    3. Import app.config as usual; this loader runs before config values are read.

Environment variables:
    NOTIFY_SSM_PARAMETER   Name of the SSM parameter (default ENVIRONMENT_VARIABLES)
    NOTIFY_CONFIG_DISABLE  If set to '1', skip loading (fallback / debugging)

Safety: Does not overwrite existing os.environ keys.
"""

from __future__ import annotations

import json
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
    raw = raw or ""
    data: Dict[str, str] = {}
    # Try JSON first
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (str, int, float, bool)) or v is None:
                    data[str(k)] = "" if v is None else str(v)
            return data
    except Exception:
        pass
    # Fallback: parse .env style
    for line in raw.splitlines():
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
    if os.getenv("NOTIFY_CONFIG_DISABLE") == "1":
        _LOG.info("config_loader disabled via NOTIFY_CONFIG_DISABLE=1")
        return
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
