"""
Regression tests for the mistune concurrency bug.

Mistune 0.8.x Markdown instances hold mutable parse state and are not thread-safe.
The fix in notification-utils uses threading.local so each thread gets its own
parser instance. These tests verify that rendering email templates concurrently
(as Celery workers do) does not produce corrupted output or raise exceptions.

See: fix/mistune-concurrency-issues in notification-utils
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from notifications_utils.template import HTMLEmailTemplate, PlainTextEmailTemplate

TEMPLATE_SAMPLES = [
    {
        "content": "Hello there",
        "subject": "Simple subject",
    },
    {
        "content": "# Heading\n\nA paragraph with **bold** text.",
        "subject": "Markdown subject",
    },
    {
        "content": "Here is a list:\n\n* item one\n* item two\n* item three\n",
        "subject": "List email",
    },
    {
        "content": "Line one\n\nLine two\n\nLine three",
        "subject": "Multi paragraph",
    },
    {
        "content": "Visit https://example.com for more info.\n\nThanks.",
        "subject": "Link email",
    },
]


def _render_html(i):
    template_dict = TEMPLATE_SAMPLES[i % len(TEMPLATE_SAMPLES)]
    return str(HTMLEmailTemplate({"content": template_dict["content"], "subject": template_dict["subject"]}))


def _render_plain_text(i):
    template_dict = TEMPLATE_SAMPLES[i % len(TEMPLATE_SAMPLES)]
    return str(PlainTextEmailTemplate({"content": template_dict["content"], "subject": template_dict["subject"]}))


@pytest.mark.parametrize(
    "render_fn, expected_count",
    [
        (_render_html, 200),
        (_render_plain_text, 200),
    ],
    ids=["HTMLEmailTemplate", "PlainTextEmailTemplate"],
)
def test_email_template_rendering_is_safe_under_concurrency(render_fn, expected_count):
    """
    Verify that rendering email templates from multiple threads concurrently does
    not raise exceptions or produce corrupted results.

    Before the fix, shared Mistune Markdown instances caused token-mismatch errors
    under concurrent load (e.g. from Celery workers).
    """
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(render_fn, i) for i in range(expected_count)]
        results = [f.result() for f in as_completed(futures)]

    assert len(results) == expected_count
    assert all(isinstance(r, str) and len(r) > 0 for r in results)


def test_html_email_template_concurrent_output_is_deterministic():
    """
    The same input must always produce the same HTML output regardless of
    which thread renders it.
    """
    template_dict = {"content": "# Hello\n\nThis is **important**.", "subject": "Test"}

    def render(_):
        return str(HTMLEmailTemplate(template_dict))

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(render, range(100)))

    assert len(set(results)) == 1, "Concurrent renders produced different HTML outputs"


def test_plain_text_email_template_concurrent_output_is_deterministic():
    """
    The same input must always produce the same plain-text output regardless of
    which thread renders it.
    """
    template_dict = {"content": "# Hello\n\nThis is **important**.", "subject": "Test"}

    def render(_):
        return str(PlainTextEmailTemplate(template_dict))

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(render, range(100)))

    assert len(set(results)) == 1, "Concurrent renders produced different plain-text outputs"
