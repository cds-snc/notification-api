#!/usr/bin/env python3
"""
Renovate Agent – automates dependency upgrades from open Renovate PRs.

Usage
-----
    python scripts/renovate_agent.py --find             # discover eligible package, write plan
    python scripts/renovate_agent.py --apply            # apply the update (edit files, regen lockfile)
    python scripts/renovate_agent.py --create-pr        # push branch and open the PR on GitHub
    python scripts/renovate_agent.py --cleanup          # delete the remote branch (on failure)
    python scripts/renovate_agent.py --comment-failure  # post failure comment on source Renovate PR

Environment variables required for --find / --create-pr / --cleanup
--------------------------------------------------------------------
    GITHUB_TOKEN  – GitHub token with repo read + write access (GitHub App token recommended)

Environment variables required for --apply
------------------------------------------
    (none beyond standard shell tools: poetry, npm)

Eligibility criteria
--------------------
    * Age   > 30 days  (from Renovate merge-confidence badge)
    * Confidence == "high" or "very high" (from Renovate merge-confidence badge)

Selection order (deterministic)
--------------------------------
    Highest age first; ties broken alphabetically by package name.

Plan file
---------
    renovate-agent-plan.json  (written by --find, read by --apply and --create-pr)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    sys.exit("requests library is required. Install with: pip install requests")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO = "cds-snc/notification-api"
BASE_BRANCH = "main"
RENOVATE_LABEL = "Renovate"
AGENT_LABEL = "renovate-agent"
PLAN_FILE = Path("renovate-agent-plan.json")
GITHUB_API = "https://api.github.com"

# Supported ecosystems and how to update them
PYPI_ECOSYSTEMS = {"pypi"}
NPM_ECOSYSTEMS = {"npm"}
NPM_PACKAGE_DIR = Path("tests_cypress")


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------


def _github_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        sys.exit("GITHUB_TOKEN environment variable is not set.")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_get(path: str, params: dict | None = None) -> list | dict:
    """Paginate through all pages of a GitHub list endpoint."""
    url = f"{GITHUB_API}{path}"
    results: list = []
    while url:
        resp = requests.get(url, headers=_github_headers(), params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            results.extend(data)
        else:
            return data
        # Follow Link header for pagination
        link = resp.headers.get("Link", "")
        next_url = None
        for part in link.split(","):
            part = part.strip()
            if 'rel="next"' in part:
                next_url = re.search(r"<([^>]+)>", part)
                next_url = next_url.group(1) if next_url else None
        url = next_url
        params = None  # params already embedded in next_url
    return results


def _gh_post(path: str, body: dict) -> dict:
    url = f"{GITHUB_API}{path}"
    resp = requests.post(url, headers=_github_headers(), json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _gh_comment(pr_number: int, comment: str) -> None:
    """Post a comment on a GitHub issue/PR."""
    _gh_post(f"/repos/{REPO}/issues/{pr_number}/comments", {"body": comment})


def _gh_delete(path: str) -> None:
    url = f"{GITHUB_API}{path}"
    resp = requests.delete(url, headers=_github_headers(), timeout=30)
    if resp.status_code not in (204, 404, 422):
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# Badge value extraction (Mend / merge-confidence SVG badges)
# ---------------------------------------------------------------------------

# Regex patterns to match mend.io badge URLs in Renovate PR bodies
_AGE_BADGE_RE = re.compile(
    r"https://developer\.mend\.io/api/mc/badges/age"
    r"/(?P<eco>[^/]+)/(?P<pkg>[^/]+)/(?P<ver>[^?|\s]+)",
    re.IGNORECASE,
)
_CONF_BADGE_RE = re.compile(
    r"https://developer\.mend\.io/api/mc/badges/confidence"
    r"/(?P<eco>[^/]+)/(?P<pkg>[^/]+)/(?P<from_ver>[^/]+)/(?P<to_ver>[^?|\s]+)",
    re.IGNORECASE,
)


def _fetch_svg(url: str) -> Optional[str]:
    """Fetch an SVG badge and return its text content, or None on error."""
    try:
        resp = requests.get(url, timeout=15, allow_redirects=True)
        if resp.status_code == 200:
            return resp.text
    except Exception as exc:
        print(f"  [warn] Could not fetch badge {url}: {exc}")
    return None


def _extract_svg_texts(svg: str) -> list[str]:
    """Return all non-empty text strings found inside <text> or <tspan> elements."""
    texts = re.findall(r"<(?:text|tspan)[^>]*>([^<]+)</(?:text|tspan)>", svg, re.IGNORECASE)
    return [t.strip() for t in texts if t.strip()]


def _parse_age_from_svg(svg: str) -> Optional[int]:
    """Extract integer days from an age badge SVG."""
    for text in _extract_svg_texts(svg):
        # Prefer explicit "N days" or "Nd" pattern to avoid false positives
        m = re.match(r"^(\d+)\s*days?$", text, re.IGNORECASE)
        if m:
            return int(m.group(1))
        m = re.match(r"^(\d+)d$", text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    # Fallback: find "N days" anywhere in the SVG text/tspan content
    m = re.search(r"(\d+)\s*days?", svg, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Last resort: isolated number in a text node, validated to be a plausible day count
    for text in _extract_svg_texts(svg):
        m = re.match(r"^(\d+)$", text)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 3650:  # 1 day to 10 years is a reasonable age range
                return val
    return None


def _parse_confidence_from_svg(svg: str) -> Optional[str]:
    """Extract confidence level string from a confidence badge SVG."""
    for text in _extract_svg_texts(svg):
        lower = text.lower().strip()
        if lower in ("very high", "high", "medium", "low", "neutral", "n/a"):
            return lower
    # Fallback: search anywhere in SVG text
    svg_lower = svg.lower()
    for level in ("very high", "high", "medium", "low", "neutral"):
        if level in svg_lower:
            return level
    return None


def _fetch_age_days(eco: str, pkg: str, version: str) -> Optional[int]:
    url = f"https://developer.mend.io/api/mc/badges/age/{eco}/{pkg}/{version}?slim=true"
    svg = _fetch_svg(url)
    if svg:
        age = _parse_age_from_svg(svg)
        if age is not None:
            return age
        print(f"  [warn] Could not parse age from badge for {pkg} {version}")
    return None


def _fetch_confidence(eco: str, pkg: str, from_ver: str, to_ver: str) -> Optional[str]:
    url = f"https://developer.mend.io/api/mc/badges/confidence/{eco}/{pkg}/{from_ver}/{to_ver}?slim=true"
    svg = _fetch_svg(url)
    if svg:
        conf = _parse_confidence_from_svg(svg)
        if conf is not None:
            return conf
        print(f"  [warn] Could not parse confidence from badge for {pkg} {from_ver}→{to_ver}")
    return None


# ---------------------------------------------------------------------------
# Renovate PR body parsing
# ---------------------------------------------------------------------------

# Matches a markdown table row that contains mend.io age AND confidence badge URLs
# Columns: Package | Change | Age (badge) | Confidence (badge)
_TABLE_ROW_RE = re.compile(
    r"\|"
    r"(?P<package_cell>[^|]+)\|"  # Package
    r"(?P<change_cell>[^|]+)\|"  # Change
    r"(?P<age_cell>[^|]+)\|"  # Age (badge image)
    r"(?P<conf_cell>[^|]+)\|",  # Confidence (badge image)
    re.IGNORECASE,
)

# Extract plain package name from "[name](url)" or just "name"
_PKG_NAME_RE = re.compile(r"\[([^\]]+)\]|\*\*([^*]+)\*\*|`([^`]+)`|^([^\s(]+)")


def _parse_package_name(cell: str) -> str:
    """Strip markdown links/formatting from a package cell."""
    cell = cell.strip()
    # Remove markdown link [text](url)
    cell = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cell)
    # Remove surrounding backticks or stars
    cell = re.sub(r"[`*]", "", cell)
    # Take first word (package name without parenthetical info)
    cell = re.sub(r"\s*\([^)]*\)", "", cell)
    return cell.strip()


def _parse_versions(change_cell: str) -> tuple[Optional[str], Optional[str]]:
    """Extract (from_version, to_version) from a Renovate change cell."""
    change_cell = change_cell.strip()
    # Markdown link: [`old` → `new`](url) or `old` → `new`
    change_cell = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", change_cell)
    change_cell = re.sub(r"`", "", change_cell)
    m = re.search(r"([\w.\-]+)\s*(?:→|->|to)\s*([\w.\-]+)", change_cell)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, None


def parse_renovate_pr_rows(body: str) -> list[dict]:
    """
    Parse all update table rows from a Renovate PR body.

    Returns a list of dicts with keys:
        package, ecosystem, from_version, to_version,
        age_badge_url, confidence_badge_url
    """
    rows = []
    for m in _TABLE_ROW_RE.finditer(body):
        pkg_cell = m.group("package_cell")
        change_cell = m.group("change_cell")
        age_cell = m.group("age_cell")
        conf_cell = m.group("conf_cell")

        # Skip header rows
        if "age" in pkg_cell.lower() or "package" in pkg_cell.lower():
            continue
        if re.match(r"\s*[-|:]+\s*", pkg_cell):
            continue

        package = _parse_package_name(pkg_cell)
        if not package:
            continue

        from_ver, to_ver = _parse_versions(change_cell)
        if not from_ver or not to_ver:
            continue

        # Extract badge URLs
        age_match = _AGE_BADGE_RE.search(age_cell)
        conf_match = _CONF_BADGE_RE.search(conf_cell)

        if not age_match or not conf_match:
            continue

        eco = age_match.group("eco").lower()
        rows.append(
            {
                "package": package,
                "ecosystem": eco,
                "from_version": from_ver,
                "to_version": to_ver,
                "age_badge_eco": age_match.group("eco"),
                "age_badge_pkg": age_match.group("pkg"),
                "age_badge_ver": age_match.group("ver"),
                "conf_badge_eco": conf_match.group("eco"),
                "conf_badge_pkg": conf_match.group("pkg"),
                "conf_badge_from": conf_match.group("from_ver"),
                "conf_badge_to": conf_match.group("to_ver"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Phase: --find
# ---------------------------------------------------------------------------


def phase_find() -> None:
    """
    Scan open Renovate PRs, find the best eligible package upgrade, write
    renovate-agent-plan.json.  Exits 0 with a message if nothing qualifies.
    """
    print("=== Phase: find ===")

    # 1. Check if a renovate-agent PR is already open
    print("Checking for existing renovate-agent PRs …")
    issues = _gh_get(f"/repos/{REPO}/issues", params={"state": "open", "labels": AGENT_LABEL, "per_page": 100})
    open_agent_prs = [i for i in issues if "pull_request" in i]
    if open_agent_prs:
        numbers = [str(i["number"]) for i in open_agent_prs]
        print(f"An open renovate-agent PR already exists (#{', #'.join(numbers)}). Skipping.")
        sys.exit(0)

    # 2. Fetch all open Renovate PRs
    print("Fetching open Renovate PRs …")
    issues = _gh_get(f"/repos/{REPO}/issues", params={"state": "open", "labels": RENOVATE_LABEL, "per_page": 100})
    renovate_prs = [i for i in issues if "pull_request" in i]
    print(f"Found {len(renovate_prs)} open Renovate PR(s).")

    # 3. Parse each PR body and fetch badge values
    candidates: list[dict] = []

    for pr in renovate_prs:
        pr_number = pr["number"]
        pr_title = pr.get("title", "")
        body = pr.get("body") or ""
        print(f"\nPR #{pr_number}: {pr_title}")

        rows = parse_renovate_pr_rows(body)
        if not rows:
            print("  No parseable update rows found.")
            continue

        for row in rows:
            pkg = row["package"]
            eco = row["ecosystem"]
            from_ver = row["from_version"]
            to_ver = row["to_version"]

            # Skip ecosystems we cannot update
            if eco not in PYPI_ECOSYSTEMS | NPM_ECOSYSTEMS:
                print(f"  Skipping {pkg} (unsupported ecosystem: {eco})")
                continue

            print(f"  Checking {pkg} {from_ver} → {to_ver} ({eco}) …", end=" ", flush=True)

            age = _fetch_age_days(row["age_badge_eco"], row["age_badge_pkg"], row["age_badge_ver"])
            confidence = _fetch_confidence(
                row["conf_badge_eco"],
                row["conf_badge_pkg"],
                row["conf_badge_from"],
                row["conf_badge_to"],
            )

            print(f"age={age} days, confidence={confidence}")

            if age is None or confidence is None:
                print("  → Skipped (could not determine age/confidence)")
                continue
            if age <= 30:
                print(f"  → Skipped (age {age} ≤ 30 days)")
                continue
            if confidence.lower() not in ("high", "very high"):
                print(f"  → Skipped (confidence '{confidence}' not 'high' or 'very high')")
                continue

            candidates.append(
                {
                    "package": pkg,
                    "ecosystem": eco,
                    "from_version": from_ver,
                    "to_version": to_ver,
                    "age_days": age,
                    "confidence": confidence,
                    "source_pr_number": pr_number,
                    "source_pr_title": pr_title,
                    "source_pr_url": pr.get("html_url") or f"https://github.com/{REPO}/pull/{pr_number}",
                }
            )

    if not candidates:
        print("\nNo eligible package upgrades found (age > 30 days AND confidence = high).")
        print("Exiting successfully – nothing to do.")
        sys.exit(0)

    # 4. Sort deterministically: highest age first, then alphabetical
    candidates.sort(key=lambda c: (-c["age_days"], c["package"].lower()))
    selected = candidates[0]

    # 5. Build branch name
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    safe_pkg = re.sub(r"[^a-zA-Z0-9._-]", "-", selected["package"]).lower()
    safe_ver = re.sub(r"[^a-zA-Z0-9._-]", "-", selected["to_version"]).lower()
    branch = f"renovate-agent/{safe_pkg}-{safe_ver}-{date_str}"
    selected["branch"] = branch

    # 6. Write plan
    PLAN_FILE.write_text(json.dumps(selected, indent=2))
    print(f"\n✔ Selected: {selected['package']} {selected['from_version']} → {selected['to_version']}")
    print(f"  Age: {selected['age_days']} days, Confidence: {selected['confidence']}")
    print(f"  Source PR: #{selected['source_pr_number']}")
    print(f"  Branch: {branch}")
    print(f"  Plan written to {PLAN_FILE}")


# ---------------------------------------------------------------------------
# Dependency update helpers
# ---------------------------------------------------------------------------


def _update_pyproject_version(content: str, package: str, new_version: str) -> str:
    """
    Replace the pinned version of *package* in pyproject.toml content.
    Handles:
      - package = "X.Y.Z"
      - package = {version = "X.Y.Z", extras = [...]}
    Case-insensitive package name matching; anchored to line start to avoid
    matching similarly-named packages (e.g. "marshmallow" vs "marshmallow-sqlalchemy").
    """
    pkg_re = re.escape(package)

    # Pattern 1: package = "version"  (simple string value, possibly with inline comment)
    new_content, n = re.subn(
        rf'(?mi)^({pkg_re}\s*=\s*)"[^"]*"',
        lambda m: f'{m.group(1)}"{new_version}"',
        content,
    )
    if n > 0:
        return new_content

    # Pattern 2: package = {version = "X.Y.Z", ...}  (dict / extras format)
    new_content, n = re.subn(
        rf'(?mi)^({pkg_re}\s*=\s*\{{[^}}]*version\s*=\s*)"[^"]*"',
        lambda m: f'{m.group(1)}"{new_version}"',
        content,
    )
    return new_content if n > 0 else content


def _update_npm_version(pkg_json_path: Path, package: str, new_version: str) -> None:
    """Update a package version in a package.json file."""
    with pkg_json_path.open() as f:
        data = json.load(f)
    updated = False
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        if package in data.get(section, {}):
            data[section][package] = new_version
            updated = True
    if not updated:
        sys.exit(f"Package '{package}' not found in {pkg_json_path}")
    with pkg_json_path.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _run(cmd: list[str], cwd: Optional[Path] = None) -> None:
    """Run a subprocess command; print combined output and exit on failure."""
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        sys.exit(f"Command failed with exit code {result.returncode}: {' '.join(cmd)}")


# ---------------------------------------------------------------------------
# Phase: --apply
# ---------------------------------------------------------------------------


def phase_apply() -> None:
    """Apply the dependency update described in renovate-agent-plan.json."""
    print("=== Phase: apply ===")
    if not PLAN_FILE.exists():
        sys.exit(f"{PLAN_FILE} not found. Run --find first.")
    plan = json.loads(PLAN_FILE.read_text())
    package = plan["package"]
    new_version = plan["to_version"]
    eco = plan["ecosystem"]

    print(f"Updating {package} → {new_version} ({eco}) …")

    if eco in PYPI_ECOSYSTEMS:
        pyproject = Path("pyproject.toml")
        content = pyproject.read_text()
        new_content = _update_pyproject_version(content, package, new_version)
        if new_content == content:
            print(f"  [warn] Could not find '{package}' version in pyproject.toml – skipping file edit.")
            print("  Will still attempt poetry update.")
        else:
            pyproject.write_text(new_content)
            print(f'  Updated pyproject.toml: {package} = "{new_version}"')
        # Regenerate poetry.lock for this package
        _run(["poetry", "update", package])

    elif eco in NPM_ECOSYSTEMS:
        pkg_json = NPM_PACKAGE_DIR / "package.json"
        if not pkg_json.exists():
            sys.exit(f"package.json not found at {pkg_json}")
        _update_npm_version(pkg_json, package, new_version)
        print(f'  Updated {pkg_json}: {package} = "{new_version}"')
        _run(["npm", "install"], cwd=NPM_PACKAGE_DIR)

    else:
        sys.exit(f"Unsupported ecosystem: {eco}")

    print("✔ Dependency update applied.")


# ---------------------------------------------------------------------------
# Phase: --create-pr
# ---------------------------------------------------------------------------


def phase_create_pr() -> None:
    """Create a GitHub PR from the pushed branch described in renovate-agent-plan.json."""
    print("=== Phase: create-pr ===")
    if not PLAN_FILE.exists():
        sys.exit(f"{PLAN_FILE} not found. Run --find first.")
    plan = json.loads(PLAN_FILE.read_text())

    package = plan["package"]
    from_ver = plan["from_version"]
    to_ver = plan["to_version"]
    age = plan["age_days"]
    confidence = plan["confidence"]
    branch = plan["branch"]
    source_pr_number = plan["source_pr_number"]
    source_pr_url = plan["source_pr_url"]
    source_pr_title = plan.get("source_pr_title", "")

    title = f"chore(deps): update {package} {from_ver} → {to_ver} [renovate-agent]"

    body = f"""\
## Renovate Agent – automated dependency upgrade

| Field | Value |
|---|---|
| **Package** | `{package}` |
| **Change** | `{from_ver}` → `{to_ver}` |
| **Ecosystem** | `{plan["ecosystem"]}` |
| **Age** | {age} days |
| **Merge Confidence** | {confidence} |
| **Source Renovate PR** | #{source_pr_number} – [{source_pr_title}]({source_pr_url}) |

### Why was this selected?

This package met the eligibility criteria:
- ✅ Age **{age} days** > 30 days
- ✅ Merge confidence is **{confidence}**

This PR was created automatically by the `renovate-agent` workflow.
Tests were run on the updated branch before this PR was opened.

### Review checklist

- [ ] Dependency update looks correct
- [ ] Tests pass (see CI)
- [ ] No unexpected changes to `pyproject.toml` / `poetry.lock`
"""

    print(f"Creating PR: {title}")
    pr_response = _gh_post(
        f"/repos/{REPO}/pulls",
        {
            "title": title,
            "body": body,
            "head": branch,
            "base": BASE_BRANCH,
        },
    )
    pr_number = pr_response["number"]
    pr_url = pr_response["html_url"]
    print(f"✔ Created PR #{pr_number}: {pr_url}")

    # Add label
    _gh_post(
        f"/repos/{REPO}/issues/{pr_number}/labels",
        {"labels": [AGENT_LABEL]},
    )
    print(f"✔ Added label '{AGENT_LABEL}' to PR #{pr_number}")


# ---------------------------------------------------------------------------
# Phase: --cleanup
# ---------------------------------------------------------------------------


def phase_cleanup() -> None:
    """Delete the remote branch created by --find (called on workflow failure)."""
    print("=== Phase: cleanup ===")
    if not PLAN_FILE.exists():
        print(f"{PLAN_FILE} not found – nothing to clean up.")
        return
    plan = json.loads(PLAN_FILE.read_text())
    branch = plan.get("branch", "")
    if not branch:
        print("No branch in plan – nothing to clean up.")
        return
    print(f"Deleting remote branch: {branch}")
    _gh_delete(f"/repos/{REPO}/git/refs/heads/{branch}")
    print(f"✔ Branch '{branch}' deleted (or did not exist).")


# ---------------------------------------------------------------------------
# Phase: --comment-failure
# ---------------------------------------------------------------------------


def phase_comment_failure(run_url: Optional[str] = None) -> None:
    """Post a failure comment on the source Renovate PR so it is visible there."""
    print("=== Phase: comment-failure ===")
    if not PLAN_FILE.exists():
        print(f"{PLAN_FILE} not found – no source PR to comment on.")
        return
    plan = json.loads(PLAN_FILE.read_text())
    source_pr_number = plan.get("source_pr_number")
    if not source_pr_number:
        print("No source_pr_number in plan – nothing to comment on.")
        return

    package = plan.get("package", "unknown")
    from_ver = plan.get("from_version", "?")
    to_ver = plan.get("to_version", "?")
    branch = plan.get("branch", "")

    run_link = f"\n\nWorkflow run: {run_url}" if run_url else ""

    comment = (
        f"⚠️ **renovate-agent**: The automated upgrade of `{package}` "
        f"`{from_ver}` → `{to_ver}` **failed the test suite**.\n\n"
        f"The branch `{branch}` has been deleted. "
        f"A human should review the failure and either fix the code or "
        f"manually skip this upgrade.{run_link}"
    )
    print(f"Posting failure comment on PR #{source_pr_number} …")
    _gh_comment(source_pr_number, comment)
    print(f"✔ Comment posted on PR #{source_pr_number}.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Renovate Agent – dependency upgrade automation")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--find", action="store_true", help="Discover eligible package")
    group.add_argument("--apply", action="store_true", help="Apply the dependency update")
    group.add_argument("--create-pr", action="store_true", help="Open the GitHub PR")
    group.add_argument("--cleanup", action="store_true", help="Delete remote branch on failure")
    group.add_argument("--comment-failure", action="store_true", help="Post failure comment on source Renovate PR")
    parser.add_argument("--run-url", default=None, help="URL of the GitHub Actions run (included in failure comment)")
    args = parser.parse_args()

    if args.find:
        phase_find()
    elif args.apply:
        phase_apply()
    elif args.create_pr:
        phase_create_pr()
    elif args.cleanup:
        phase_cleanup()
    elif args.comment_failure:
        phase_comment_failure(run_url=args.run_url)


if __name__ == "__main__":
    main()
