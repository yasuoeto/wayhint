"""GDK clipboard. Imported only by the UI layer."""

from __future__ import annotations

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk  # noqa: E402


def copy_text(text: str) -> bool:
    display = Gdk.Display.get_default()
    if display is None:
        return False
    display.get_clipboard().set(text)
    return True
