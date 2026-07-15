#!/usr/bin/env python3
"""Validate the OpenAPI spec YAML files.

Runs as part of ``make test`` to catch malformed OpenAPI specs before they are
shipped. The checks are intentionally dependency-free (PyYAML only) so they can
run without pulling in an OpenAPI validator that conflicts with the pinned
``jsonschema`` version.

Checks performed for each spec file:
  * the file is syntactically valid YAML
  * no mapping contains duplicate keys (PyYAML silently keeps the last one)
  * the required top-level OpenAPI sections are present
  * ``info`` declares a ``title`` and ``version``
  * every local ``$ref`` (``#/...``) resolves to an existing node
"""

import os
import sys

import yaml  # type: ignore

SPEC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "openapi")
SPEC_FILES = [
    "v2-notifications-api-en.yaml",
    "v2-notifications-api-fr.yaml",
]

REQUIRED_TOP_LEVEL_KEYS = ["openapi", "info", "paths"]
REQUIRED_INFO_KEYS = ["title", "version"]


class _DuplicateKeyError(Exception):
    pass


class _UniqueKeyLoader(yaml.SafeLoader):
    """A SafeLoader that raises on duplicate mapping keys instead of silently
    keeping the last value."""


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict:
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in mapping:
            raise _DuplicateKeyError(f"duplicate key {key!r} at line {key_node.start_mark.line + 1}")
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _resolve_ref(spec: dict, ref: str) -> bool:
    """Return True if a local ``#/a/b/c`` reference resolves within the spec."""
    node = spec
    for part in ref.lstrip("#/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return False
    return True


def _collect_broken_refs(node, spec: dict, broken: list) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str) and value.startswith("#/"):
                if not _resolve_ref(spec, value):
                    broken.append(value)
            else:
                _collect_broken_refs(value, spec, broken)
    elif isinstance(node, list):
        for item in node:
            _collect_broken_refs(item, spec, broken)


def validate_spec(path: str) -> list:
    """Validate a single spec file and return a list of error messages."""
    errors: list = []
    with open(path, "r") as f:
        try:
            spec = yaml.load(f, Loader=_UniqueKeyLoader)
        except (yaml.YAMLError, _DuplicateKeyError) as exc:
            return [f"invalid YAML: {exc}"]

    if not isinstance(spec, dict):
        return ["top-level document is not a mapping"]

    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in spec:
            errors.append(f"missing required top-level key '{key}'")

    info = spec.get("info")
    if isinstance(info, dict):
        for key in REQUIRED_INFO_KEYS:
            if key not in info:
                errors.append(f"missing required 'info.{key}'")
    elif "info" in spec:
        errors.append("'info' is not a mapping")

    broken_refs: list = []
    _collect_broken_refs(spec, spec, broken_refs)
    for ref in sorted(set(broken_refs)):
        errors.append(f"unresolved $ref '{ref}'")

    return errors


def main() -> int:
    exit_code = 0
    for filename in SPEC_FILES:
        path = os.path.join(SPEC_DIR, filename)
        if not os.path.exists(path):
            print(f"\033[31m{filename}: file not found\033[0m")
            exit_code = 1
            continue

        errors = validate_spec(path)
        if errors:
            exit_code = 1
            print(f"\033[31m{filename}: {len(errors)} error(s)\033[0m")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"\033[32m{filename}: OK\033[0m")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
