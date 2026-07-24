#!/usr/bin/env python3
"""
One-time bootstrap script: converts existing v2-notifications-api-en.yaml and
v2-notifications-api-fr.yaml into a Jinja2 template (v2-notifications-api.yaml.j2)
and a translations CSV (openapi/translations/fr.csv).

Re-run this script if you ever want to re-derive the template from a pair of hand-edited
EN/FR YAML files.  Normally you should edit the .j2 template and fr.csv directly and use
generate_openapi.py to regenerate the output files.

Usage:
    python scripts/bootstrap_openapi_template.py
"""

import csv
import re
from pathlib import Path

OPENAPI_DIR = Path(__file__).parent.parent / "openapi"
EN_FILE = OPENAPI_DIR / "v2-notifications-api-en.yaml"
FR_FILE = OPENAPI_DIR / "v2-notifications-api-fr.yaml"
TEMPLATE_FILE = OPENAPI_DIR / "v2-notifications-api.yaml.j2"
TRANSLATIONS_DIR = OPENAPI_DIR / "translations"


def jinja_t(value: str) -> str:
    """Wrap *value* in a Jinja2 ``{{ t(...) }}`` call.

    Chooses single vs. double quotes for the inner string so that it never
    conflicts with the value's own quote characters.  Also escapes backslashes
    so that YAML escape sequences like ``\\n`` are preserved as literal
    backslash-n in the Jinja2 string (rather than being reinterpreted as a
    newline by Jinja2's Python-like expression parser).

    Raises if the value contains both single and double quotes (extremely
    unlikely in OpenAPI prose).
    """
    has_double = '"' in value
    has_single = "'" in value
    if has_double and has_single:
        raise ValueError(f"Value contains both ' and \" — cannot auto-generate t() call.\n  value: {value!r}")
    # Escape backslashes so that e.g. a literal \n in the value is written as
    # \\n in the Jinja2 string literal and therefore round-trips correctly.
    escaped = value.replace("\\", "\\\\")
    if has_double:
        return f"{{{{ t('{escaped}') }}}}"
    return f'{{{{ t("{escaped}") }}}}'


def main() -> None:
    TRANSLATIONS_DIR.mkdir(exist_ok=True)
    csv_path = TRANSLATIONS_DIR / "fr.csv"

    en_lines = EN_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
    # Ensure EN ends with newline for a clean template output
    if en_lines and not en_lines[-1].endswith("\n"):
        en_lines[-1] += "\n"
    fr_lines = FR_FILE.read_text(encoding="utf-8").splitlines(keepends=True)

    translations: dict[str, str] = {}
    template_lines: list[str] = []

    # Use difflib to align EN and FR lines.  In the vast majority of cases the
    # files are identical in structure (1:1 replacements only), but we use the
    # general alignment to handle the rare blank-line discrepancy gracefully.
    import difflib

    matcher = difflib.SequenceMatcher(None, en_lines, fr_lines, autojunk=False)

    def process_pair(en_line: str, fr_line: str, lineno: int) -> None:
        """Translate one EN→FR line pair and append the result to template_lines."""
        if en_line == fr_line:
            template_lines.append(en_line)
            return

        en_s = en_line.rstrip("\n")
        fr_s = fr_line.rstrip("\n")
        handled = False

        # ------------------------------------------------------------------
        # Pattern 1: YAML key-value line  →  <indent><key>: <value>
        # Handles both plain and double-quoted values.
        # ------------------------------------------------------------------
        m_en = re.match(r"^(\s*[\w\-]+:\s+)(.+)$", en_s)
        m_fr = re.match(r"^(\s*[\w\-]+:\s+)(.+)$", fr_s)
        if m_en and m_fr and m_en.group(1) == m_fr.group(1):
            prefix = m_en.group(1)
            en_val = m_en.group(2)
            fr_val = m_fr.group(2)

            # Strip surrounding YAML double-quotes when present so the CSV
            # keys are clean prose strings, not YAML-quoted strings.
            if en_val.startswith('"') and en_val.endswith('"'):
                en_inner = en_val[1:-1]
                fr_inner = fr_val[1:-1] if (fr_val.startswith('"') and fr_val.endswith('"')) else fr_val
                translations[en_inner] = fr_inner
                template_lines.append(f'{prefix}"{jinja_t(en_inner)}"\n')
            else:
                translations[en_val] = fr_val
                template_lines.append(f"{prefix}{jinja_t(en_val)}\n")
            handled = True

        # ------------------------------------------------------------------
        # Pattern 2: YAML list item  →  <indent>- <value>
        # Handles items like:  - ["email address", "name"]
        # ------------------------------------------------------------------
        if not handled:
            m_en2 = re.match(r"^(\s*-\s+)(.+)$", en_s)
            m_fr2 = re.match(r"^(\s*-\s+)(.+)$", fr_s)
            if m_en2 and m_fr2 and m_en2.group(1) == m_fr2.group(1):
                prefix = m_en2.group(1)
                en_val = m_en2.group(2)
                fr_val = m_fr2.group(2)
                translations[en_val] = fr_val
                template_lines.append(f"{prefix}{jinja_t(en_val)}\n")
                handled = True

        # ------------------------------------------------------------------
        # Pattern 3: Bare text content (lines inside YAML block scalars, e.g. |)
        # ------------------------------------------------------------------
        if not handled:
            m_en3 = re.match(r"^(\s+)(\S.+)$", en_s)
            m_fr3 = re.match(r"^(\s+)(\S.+)$", fr_s)
            if m_en3 and m_fr3 and m_en3.group(1) == m_fr3.group(1):
                indent = m_en3.group(1)
                en_text = m_en3.group(2)
                fr_text = m_fr3.group(2)
                translations[en_text] = fr_text
                template_lines.append(f"{indent}{jinja_t(en_text)}\n")
                handled = True

        if not handled:
            print(f"WARNING line {lineno}: unhandled diff")
            print(f"  EN: {en_s!r}")
            print(f"  FR: {fr_s!r}")
            template_lines.append(en_line)

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        en_block = en_lines[i1:i2]
        fr_block = fr_lines[j1:j2]

        if op == "equal":
            template_lines.extend(en_block)

        elif op == "replace":
            # Pair up as many lines as possible; keep any excess EN lines as-is.
            for idx, (en_line, fr_line) in enumerate(zip(en_block, fr_block)):
                process_pair(en_line, fr_line, i1 + idx + 1)
            for en_line in en_block[len(fr_block) :]:
                template_lines.append(en_line)  # extra EN-only lines (e.g. blank lines)

        elif op == "delete":
            # Lines only in EN (not in FR) — keep as-is in the template.
            template_lines.extend(en_block)

        elif op == "insert":
            # Lines only in FR — no EN equivalent; cannot include in template.
            pass

    TEMPLATE_FILE.write_text("".join(template_lines), encoding="utf-8")
    print(f"Written template  : {TEMPLATE_FILE}")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(["english", "french"])
        for en, fr in sorted(translations.items(), key=lambda x: x[0].lower()):
            writer.writerow([en, fr])
    print(f"Written CSV       : {csv_path}  ({len(translations)} pairs)")


if __name__ == "__main__":
    main()
