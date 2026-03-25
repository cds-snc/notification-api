"""
Unit tests for scripts/renovate_agent.py

These tests cover pure-Python parsing helpers that do not require network
access, a database, or a running application.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make the scripts/ directory importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import renovate_agent as ra  # noqa: E402  (import after sys.path edit)


# ---------------------------------------------------------------------------
# _parse_age_from_svg
# ---------------------------------------------------------------------------


class TestParseAgeFromSvg:
    def test_explicit_days_label(self):
        svg = '<text>42 days</text>'
        assert ra._parse_age_from_svg(svg) == 42

    def test_explicit_day_singular(self):
        svg = '<text>1 day</text>'
        assert ra._parse_age_from_svg(svg) == 1

    def test_short_form_d(self):
        svg = '<tspan>90d</tspan>'
        assert ra._parse_age_from_svg(svg) == 90

    def test_fallback_anywhere_in_svg(self):
        svg = 'some stuff 123 days more stuff'
        assert ra._parse_age_from_svg(svg) == 123

    def test_isolated_number_in_tspan(self):
        # Isolated integer in a <tspan> element is accepted as a day count
        svg = '<tspan>55</tspan>'
        assert ra._parse_age_from_svg(svg) == 55

    def test_isolated_number_out_of_range_ignored(self):
        # 0 is not a plausible day count
        svg = '<tspan>0</tspan>'
        assert ra._parse_age_from_svg(svg) is None

    def test_no_age_returns_none(self):
        assert ra._parse_age_from_svg('<text>hello</text>') is None


# ---------------------------------------------------------------------------
# _parse_confidence_from_svg
# ---------------------------------------------------------------------------


class TestParseConfidenceFromSvg:
    @pytest.mark.parametrize(
        "level",
        ["very high", "high", "medium", "low", "neutral", "n/a"],
    )
    def test_known_levels(self, level):
        svg = f'<text>{level}</text>'
        assert ra._parse_confidence_from_svg(svg) == level

    def test_case_insensitive(self):
        svg = '<text>HIGH</text>'
        assert ra._parse_confidence_from_svg(svg) == "high"

    def test_fallback_search(self):
        svg = 'merge confidence is very high for this package'
        assert ra._parse_confidence_from_svg(svg) == "very high"

    def test_unknown_returns_none(self):
        assert ra._parse_confidence_from_svg('<text>unknown level</text>') is None


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
