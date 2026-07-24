#!/usr/bin/env python3
"""
Split existing combined OpenAPI spec files into source parts under openapi/src/.

This script is used to initialize the src/ directory structure from the
existing combined files. Run it once when setting up the split structure,
or again if you need to re-sync src/ from the combined files.

Usage:
    cd openapi && python split.py
    # or from workspace root:
    python openapi/split.py
"""

from pathlib import Path

import yaml

# Path routing rules — order matters (more specific first)
PATH_GROUPS = [
    ("notifications", lambda p: p.startswith("/v2/notifications")),
    ("manage-templates", lambda p: p.startswith("/v2/manage-template")),
    ("templates", lambda p: p.startswith("/v2/template")),
]

DUMPER_KWARGS = dict(default_flow_style=False, allow_unicode=True, sort_keys=False, indent=2)


def split_spec(lang: str, openapi_dir: Path) -> None:
    input_file = openapi_dir / f"v2-notifications-api-{lang}.yaml"
    print(f"Reading {input_file}...")

    with open(input_file) as f:
        spec = yaml.safe_load(f)

    src_dir = openapi_dir / "src"
    src_dir.mkdir(exist_ok=True)
    (src_dir / "paths").mkdir(exist_ok=True)

    # base.{lang}.yaml: everything except paths and components
    base = {k: v for k, v in spec.items() if k not in ("paths", "components")}
    base_file = src_dir / f"base.{lang}.yaml"
    with open(base_file, "w") as f:
        yaml.dump(base, f, **DUMPER_KWARGS)
    print(f"  Wrote {base_file}")

    # Split paths into groups
    all_paths = spec.get("paths", {})
    path_groups: dict[str, dict] = {name: {} for name, _ in PATH_GROUPS}
    unmatched: dict[str, object] = {}

    for path_key, path_value in all_paths.items():
        matched = False
        for group_name, matcher in PATH_GROUPS:
            if matcher(path_key):
                path_groups[group_name][path_key] = path_value
                matched = True
                break
        if not matched:
            unmatched[path_key] = path_value
            print(f"  Warning: unmatched path '{path_key}' — add it to PATH_GROUPS in split.py")

    for group_name, paths_dict in path_groups.items():
        path_file = src_dir / "paths" / f"{group_name}.{lang}.yaml"
        with open(path_file, "w") as f:
            yaml.dump({"paths": paths_dict}, f, **DUMPER_KWARGS)
        print(f"  Wrote {path_file}  ({len(paths_dict)} path(s))")

    # components.{lang}.yaml
    components_file = src_dir / f"components.{lang}.yaml"
    with open(components_file, "w") as f:
        yaml.dump({"components": spec.get("components", {})}, f, **DUMPER_KWARGS)
    print(f"  Wrote {components_file}")


def main() -> None:
    openapi_dir = Path(__file__).parent
    for lang in ("en", "fr"):
        split_spec(lang, openapi_dir)
    print("\nDone. Source files created in openapi/src/")
    print("Run 'python openapi/build.py' to rebuild the combined files.")


if __name__ == "__main__":
    main()
