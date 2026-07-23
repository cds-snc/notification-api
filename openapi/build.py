#!/usr/bin/env python3
"""
Build combined OpenAPI spec files from source parts.

Reads openapi/src/ and assembles the final v2-notifications-api-{en,fr}.yaml
files. The manifest controls which path files are included, allowing
unreleased endpoints to be excluded from production builds.

Usage:
    python openapi/build.py                      # uses production manifest
    python openapi/build.py --manifest staging   # includes unreleased paths

Manifests live in openapi/manifests/{name}.yaml.
Source parts live in openapi/src/:
  base.{lang}.yaml          — openapi/info/servers/tags
  paths/{name}.{lang}.yaml  — individual path groups
  components.{lang}.yaml    — all schemas and security schemes
"""

import argparse
import sys
from pathlib import Path

import yaml

DUMPER_KWARGS = dict(default_flow_style=False, allow_unicode=True, sort_keys=False, indent=2)

GENERATED_HEADER = """\
# AUTO-GENERATED — do not edit directly.
# Edit source files in openapi/src/ then run:
#   python openapi/build.py
#
"""


def build(manifest_name: str) -> None:
    openapi_dir = Path(__file__).parent
    src_dir = openapi_dir / "src"
    manifest_path = openapi_dir / "manifests" / f"{manifest_name}.yaml"

    if not manifest_path.exists():
        print(f"Error: manifest '{manifest_name}' not found at {manifest_path}", file=sys.stderr)
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = yaml.safe_load(f)

    path_names: list[str] = manifest.get("paths", [])

    for lang in ("en", "fr"):
        # Start from base (openapi, info, externalDocs, servers, tags)
        base_file = src_dir / f"base.{lang}.yaml"
        with open(base_file) as f:
            spec: dict = yaml.safe_load(f)

        # Merge paths in manifest order
        spec["paths"] = {}
        for path_name in path_names:
            path_file = src_dir / "paths" / f"{path_name}.{lang}.yaml"
            if not path_file.exists():
                print(f"Warning: {path_file} not found, skipping", file=sys.stderr)
                continue
            with open(path_file) as f:
                paths_data = yaml.safe_load(f)
            if paths_data and "paths" in paths_data:
                spec["paths"].update(paths_data["paths"])

        # Add components
        components_file = src_dir / f"components.{lang}.yaml"
        with open(components_file) as f:
            components_data = yaml.safe_load(f)
        if components_data and "components" in components_data:
            spec["components"] = components_data["components"]

        output_file = openapi_dir / f"v2-notifications-api-{lang}.yaml"
        with open(output_file, "w") as f:
            f.write(GENERATED_HEADER)
            yaml.dump(spec, f, **DUMPER_KWARGS)

        print(f"  Built {output_file}")

    print(f"Done (manifest: {manifest_name})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build OpenAPI spec files from source parts")
    parser.add_argument(
        "--manifest",
        default="production",
        help="Manifest name (default: production). Manifests are in openapi/manifests/.",
    )
    args = parser.parse_args()
    build(args.manifest)


if __name__ == "__main__":
    main()
