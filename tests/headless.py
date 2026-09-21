"""The headless session, gated for unittest.

The session itself lives in ``tools/headless.py`` so that ``scripts/demo`` can drive the same
compositor, daemon and capture path without importing the test suite. This module only adds what
a test needs on top: the opt-in flag and the skip decorators. ``./scripts/check-gui`` is the
entry point; ``./scripts/check`` leaves these tests skipped.
"""

from __future__ import annotations

import os
import shutil
import unittest

from tools.headless import INJECT, HeadlessSession, difference_box, missing

ENABLE = "WAYHINT_GUI_TESTS"

__all__ = [
    "ENABLE",
    "HeadlessSession",
    "difference_box",
    "needs_headless",
    "needs_key_injection",
    "requirements",
]


def requirements() -> str | None:
    """What is missing, or ``None`` when the GUI tests can run here."""
    if os.environ.get(ENABLE) != "1":
        return f"{ENABLE} is not set (run ./scripts/check-gui)"
    return missing()


needs_headless = unittest.skipUnless(requirements() is None, requirements() or "")
needs_key_injection = unittest.skipUnless(
    requirements() is None and shutil.which(INJECT) is not None,
    requirements() or f"{INJECT} is not on PATH",
)
