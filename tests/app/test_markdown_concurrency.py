"""
Regression tests for the mistune concurrency bug.

Mistune 0.8.x Markdown instances hold mutable parse state and are not thread-safe.
The fix in notification-utils wraps each renderer in a thread-local factory so
each thread gets its own parser instance.

The root cause: the old code created module-level mistune.Markdown singletons
(e.g. `notify_email_markdown = mistune.Markdown(...)`). Under concurrent Celery
thread-pool workers those shared instances had their parse state overwritten by
other threads, producing token-mismatch errors in production.

The fix: each renderer is now a plain Python function that lazily creates a
per-thread mistune.Markdown instance via threading.local.

These tests verify the fix is in place. Note: simply rendering templates
concurrently is NOT a reliable way to detect this bug — Python's GIL prevents
true parallelism for pure-Python code, so the race condition rarely triggers in
tests even with the broken code. Instead we assert properties of the fix
itself: that the formatters are functions (not shared objects) and that they
hand each thread an isolated parser instance.

See: fix/mistune-concurrency-issues in notification-utils
"""

import inspect
import threading

import mistune
import pytest
from notifications_utils import formatters

# The four rendering functions that were previously shared Markdown singletons.
FORMATTER_NAMES = [
    "notify_email_markdown",
    "notify_plain_text_email_markdown",
    "notify_email_preheader_markdown",
    "notify_letter_preview_markdown",
]


@pytest.mark.parametrize("name", FORMATTER_NAMES)
def test_markdown_formatter_is_a_function_not_a_shared_instance(name):
    """
    Before the fix each formatter was a module-level mistune.Markdown object.
    After the fix each formatter must be a plain Python function that wraps a
    thread-local Markdown instance.

    This test FAILS on notification-utils <= 53.2.29 (the buggy release) and
    PASSES on the fixed release.
    """
    fn = getattr(formatters, name)
    assert inspect.isfunction(fn), (
        f"notifications_utils.formatters.{name} is a {type(fn).__name__}, not a function. "
        "This means a shared mistune.Markdown instance is being used across threads "
        "(the concurrency bug). Upgrade notification-utils to the version that introduces "
        "thread-local markdown renderers."
    )


@pytest.mark.parametrize("name", FORMATTER_NAMES)
def test_each_thread_gets_an_isolated_markdown_instance(name):
    """
    The fix stores a separate mistune.Markdown object per thread in threading.local.
    Verify that two threads calling the same formatter function never share the
    same underlying Markdown parser object.

    This test FAILS on the buggy release (there is only one shared instance so
    both threads see the same id()) and PASSES on the fixed release.
    """
    fn = getattr(formatters, name)
    collected = {}
    barrier = threading.Barrier(2)

    def capture(thread_id):
        # Warm up the thread-local so the instance is created.
        fn("hello")
        barrier.wait()  # ensure both threads are alive at the same time
        # Read back the instance that was stored for this thread.
        collected[thread_id] = getattr(formatters._markdown_local, name, None)

    t1 = threading.Thread(target=capture, args=(1,))
    t2 = threading.Thread(target=capture, args=(2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    instance_1 = collected[1]
    instance_2 = collected[2]

    assert instance_1 is not None, f"Thread 1 did not create a {name} instance"
    assert instance_2 is not None, f"Thread 2 did not create a {name} instance"
    assert isinstance(instance_1, mistune.Markdown)
    assert isinstance(instance_2, mistune.Markdown)
    assert instance_1 is not instance_2, (
        f"Both threads share the same mistune.Markdown instance for {name}. " "The thread-safety fix is not in place."
    )
