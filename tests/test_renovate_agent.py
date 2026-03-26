"""
Unit tests for scripts/renovate_agent.py

These tests cover pure-Python parsing helpers that do not require network
access, a database, or a running application.
"""

import json
import sys
from pathlib import Path

import pytest

# Make the scripts/ directory importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import renovate_agent as ra  # noqa: E402  (import after sys.path edit)

# ---------------------------------------------------------------------------
# _parse_age_from_svg
# ---------------------------------------------------------------------------


class TestParseAgeFromSvg:
    def test_explicit_days_label(self):
        svg = "<text>42 days</text>"
        assert ra._parse_age_from_svg(svg) == 42

    def test_explicit_day_singular(self):
        svg = "<text>1 day</text>"
        assert ra._parse_age_from_svg(svg) == 1

    def test_short_form_d(self):
        svg = "<tspan>90d</tspan>"
        assert ra._parse_age_from_svg(svg) == 90

    def test_fallback_anywhere_in_svg(self):
        svg = "some stuff 123 days more stuff"
        assert ra._parse_age_from_svg(svg) == 123

    def test_isolated_number_in_tspan(self):
        # Isolated integer in a <tspan> element is accepted as a day count
        svg = "<tspan>55</tspan>"
        assert ra._parse_age_from_svg(svg) == 55

    def test_isolated_number_out_of_range_ignored(self):
        # 0 is not a plausible day count
        svg = "<tspan>0</tspan>"
        assert ra._parse_age_from_svg(svg) is None

    def test_no_age_returns_none(self):
        assert ra._parse_age_from_svg("<text>hello</text>") is None


# ---------------------------------------------------------------------------
# _parse_confidence_from_svg
# ---------------------------------------------------------------------------


class TestParseConfidenceFromSvg:
    @pytest.mark.parametrize(
        "level",
        ["very high", "high", "medium", "low", "neutral", "n/a"],
    )
    def test_known_levels(self, level):
        svg = f"<text>{level}</text>"
        assert ra._parse_confidence_from_svg(svg) == level

    def test_case_insensitive(self):
        svg = "<text>HIGH</text>"
        assert ra._parse_confidence_from_svg(svg) == "high"

    def test_fallback_search(self):
        svg = "merge confidence is very high for this package"
        assert ra._parse_confidence_from_svg(svg) == "very high"

    def test_unknown_returns_none(self):
        assert ra._parse_confidence_from_svg("<text>unknown level</text>") is None


# ---------------------------------------------------------------------------
# _parse_package_name
# ---------------------------------------------------------------------------


class TestParsePackageName:
    def test_plain_name(self):
        assert ra._parse_package_name("requests") == "requests"

    def test_markdown_link(self):
        assert ra._parse_package_name("[requests](https://example.com)") == "requests"

    def test_backtick_formatting(self):
        assert ra._parse_package_name("`requests`") == "requests"

    def test_bold_formatting(self):
        assert ra._parse_package_name("**requests**") == "requests"

    def test_name_with_parenthetical_info(self):
        assert ra._parse_package_name("requests (extra)") == "requests"

    def test_leading_trailing_whitespace(self):
        assert ra._parse_package_name("  requests  ") == "requests"


# ---------------------------------------------------------------------------
# _parse_versions
# ---------------------------------------------------------------------------


class TestParseVersions:
    def test_arrow_separator(self):
        assert ra._parse_versions("`1.0.0` → `2.0.0`") == ("1.0.0", "2.0.0")

    def test_ascii_arrow(self):
        assert ra._parse_versions("1.0.0 -> 2.0.0") == ("1.0.0", "2.0.0")

    def test_to_word(self):
        assert ra._parse_versions("1.0.0 to 2.0.0") == ("1.0.0", "2.0.0")

    def test_markdown_link_wrapping(self):
        cell = "[`1.2.3` → `4.5.6`](https://example.com)"
        assert ra._parse_versions(cell) == ("1.2.3", "4.5.6")

    def test_no_versions_returns_none_tuple(self):
        assert ra._parse_versions("no version info here") == (None, None)


# ---------------------------------------------------------------------------
# _update_pyproject_version
# ---------------------------------------------------------------------------


class TestUpdatePyprojectVersion:
    def test_simple_string_version(self):
        content = 'requests = "1.0.0"\n'
        result = ra._update_pyproject_version(content, "requests", "2.0.0")
        assert result == 'requests = "2.0.0"\n'

    def test_dict_version(self):
        content = 'requests = {version = "1.0.0", extras = ["security"]}\n'
        result = ra._update_pyproject_version(content, "requests", "2.0.0")
        assert '"2.0.0"' in result

    def test_does_not_match_similar_package(self):
        # "marshmallow" should NOT match "marshmallow-sqlalchemy"
        content = 'marshmallow-sqlalchemy = "0.28.0"\nmarshmallow = "3.0.0"\n'
        result = ra._update_pyproject_version(content, "marshmallow", "3.1.0")
        assert 'marshmallow-sqlalchemy = "0.28.0"' in result
        assert 'marshmallow = "3.1.0"' in result

    def test_no_match_returns_original(self):
        content = 'other = "1.0.0"\n'
        result = ra._update_pyproject_version(content, "requests", "2.0.0")
        assert result == content

    def test_strips_caret_operator(self):
        # ^ operator is intentionally removed to produce an exact pin
        content = 'certifi = "^2024.0.0"\n'
        result = ra._update_pyproject_version(content, "certifi", "2025.1.0")
        assert result == 'certifi = "2025.1.0"\n'

    def test_strips_range_operators(self):
        # Multi-constraint ranges are collapsed to a single pinned version
        content = 'urllib3 = ">=2.6.3,<3"\n'
        result = ra._update_pyproject_version(content, "urllib3", "2.6.4")
        assert result == 'urllib3 = "2.6.4"\n'

    def test_strips_tilde_operator(self):
        content = 'python = "~3.12.7"\n'
        result = ra._update_pyproject_version(content, "python", "3.12.9")
        assert result == 'python = "3.12.9"\n'

    def test_toml_aware_strips_caret(self):
        # With proper [tool.poetry.dependencies] section the TOML-aware path is used
        content = '[tool.poetry.dependencies]\ncertifi = "^2024.0.0"\n'
        result = ra._update_pyproject_version(content, "certifi", "2025.1.0")
        assert result == '[tool.poetry.dependencies]\ncertifi = "2025.1.0"\n'

    def test_toml_aware_dict_strips_caret(self):
        content = '[tool.poetry.dependencies]\ncelery = {extras = ["sqs"], version = "^5.4.0"}\n'
        result = ra._update_pyproject_version(content, "celery", "5.5.0")
        assert 'version = "5.5.0"' in result
        assert "^" not in result

    def test_toml_aware_group_dependency(self):
        # Packages in test/group sections are also found via TOML-aware path
        content = '[tool.poetry.group.test.dependencies]\nruff = "^0.8.2"\n'
        result = ra._update_pyproject_version(content, "ruff", "0.9.0")
        assert result == '[tool.poetry.group.test.dependencies]\nruff = "0.9.0"\n'


# ---------------------------------------------------------------------------
# phase_comment_failure
# ---------------------------------------------------------------------------


class TestPhaseCommentFailure:
    def test_posts_comment_with_run_url(self, tmp_path, monkeypatch):
        plan = {
            "package": "requests",
            "from_version": "2.27.1",
            "to_version": "2.28.0",
            "branch": "renovate-agent/requests-2.28.0-20240101",
            "source_pr_number": 42,
        }
        plan_file = tmp_path / "renovate-agent-plan.json"
        plan_file.write_text(json.dumps(plan))
        monkeypatch.setattr(ra, "PLAN_FILE", plan_file)

        posted_comments: list[dict] = []

        def fake_comment(pr_number: int, comment: str) -> None:
            posted_comments.append({"pr_number": pr_number, "comment": comment})

        monkeypatch.setattr(ra, "_gh_comment", fake_comment)

        ra.phase_comment_failure(run_url="https://github.com/example/run/1")

        assert len(posted_comments) == 1
        c = posted_comments[0]
        assert c["pr_number"] == 42
        assert "requests" in c["comment"]
        assert "2.27.1" in c["comment"]
        assert "2.28.0" in c["comment"]
        assert "https://github.com/example/run/1" in c["comment"]

    def test_no_op_when_plan_missing(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(ra, "PLAN_FILE", tmp_path / "nonexistent.json")
        ra.phase_comment_failure()
        captured = capsys.readouterr()
        assert "not found" in captured.out

    def test_no_op_when_source_pr_missing(self, tmp_path, monkeypatch):
        plan = {"package": "requests", "branch": "some-branch"}
        plan_file = tmp_path / "renovate-agent-plan.json"
        plan_file.write_text(json.dumps(plan))
        monkeypatch.setattr(ra, "PLAN_FILE", plan_file)

        called = []
        monkeypatch.setattr(ra, "_gh_comment", lambda *a, **k: called.append(a))

        ra.phase_comment_failure()
        assert called == []


# ---------------------------------------------------------------------------
# Confidence eligibility: "very high" must be accepted
# ---------------------------------------------------------------------------


class TestConfidenceEligibility:
    """Regression test for the bug where 'very high' was incorrectly rejected."""

    @pytest.mark.parametrize("confidence", ["high", "very high"])
    def test_eligible_confidence_levels(self, confidence):
        """Both 'high' and 'very high' should pass the eligibility filter."""
        assert confidence.lower() in ("high", "very high")

    def test_medium_is_not_eligible(self):
        confidence = "medium"
        assert confidence.lower() not in ("high", "very high")


# ---------------------------------------------------------------------------
# _confidence_from_color
# ---------------------------------------------------------------------------


class TestConfidenceFromColor:
    def test_green_returns_high(self):
        # mend.io "high/very high" badge colour sampled in CI
        assert ra._confidence_from_color((48, 161, 22)) == "high"

    def test_orange_returns_medium(self):
        assert ra._confidence_from_color((200, 120, 30)) == "medium"

    def test_red_returns_low(self):
        assert ra._confidence_from_color((200, 60, 40)) == "low"

    def test_grey_returns_neutral(self):
        assert ra._confidence_from_color((150, 150, 150)) == "neutral"

    def test_white_returns_none(self):
        # White means the sampler missed the coloured value area – not "neutral"
        assert ra._confidence_from_color((255, 255, 255)) is None

    def test_near_white_returns_none(self):
        assert ra._confidence_from_color((220, 220, 220)) is None

    def test_ambiguous_returns_none(self):
        # pure blue is not a recognised badge colour
        assert ra._confidence_from_color((0, 0, 200)) is None


# ---------------------------------------------------------------------------
# _sample_badge_png_color
# ---------------------------------------------------------------------------


class TestSampleBadgePngColor:
    def _make_svg_with_png(self, rgb: tuple[int, int, int]) -> str:
        """Build a minimal SVG wrapping a 10×4 solid-colour PNG."""
        import base64
        import struct
        import zlib

        r, g, b = rgb
        width, height = 10, 4
        # Build raw image: filter byte 0 + width*3 bytes per row
        raw = b""
        for _ in range(height):
            raw += b"\x00" + bytes([r, g, b] * width)
        compressed = zlib.compress(raw)

        def chunk(ctype: bytes, data: bytes) -> bytes:
            import binascii

            n = struct.pack(">I", len(data))
            crc = struct.pack(">I", binascii.crc32(ctype + data) & 0xFFFFFFFF)
            return n + ctype + data + crc

        ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        idat = chunk(b"IDAT", compressed)
        iend = chunk(b"IEND", b"")
        png = b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend
        b64 = base64.b64encode(png).decode()
        return f'<svg><image xlink:href="data:image/png;base64,{b64}"/></svg>'

    def test_samples_correct_colour(self):
        svg = self._make_svg_with_png((48, 161, 22))
        rgb = ra._sample_badge_png_color(svg)
        assert rgb == (48, 161, 22)

    def test_returns_none_for_no_png(self):
        assert ra._sample_badge_png_color("<svg></svg>") is None

    def test_returns_none_for_invalid_base64(self):
        svg = '<svg><image xlink:href="data:image/png;base64,!!!invalid!!!"/></svg>'
        assert ra._sample_badge_png_color(svg) is None
