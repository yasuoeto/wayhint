"""Default CSS plus the user's ``style.css`` (optional)."""

from __future__ import annotations

import logging
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

log = logging.getLogger(__name__)

DEFAULT_CSS = b"""
window.wayhint { background-color: alpha(#1e1e2e, 0.92); color: #cdd6f4; border-radius: 10px; }
.wayhint-header { padding: 8px 12px; font-weight: bold; font-size: 1.05em; }
.wayhint-context { padding: 0 12px 6px 12px; opacity: 0.7; font-size: 0.85em; }
.wayhint-error { background-color: alpha(#f38ba8, 0.25); color: #f38ba8; padding: 6px 12px; }
.wayhint-row { padding: 4px 12px; }
.wayhint-row.favorite .wayhint-title { font-weight: bold; }
.wayhint-key { font-family: monospace; color: #89b4fa; min-width: 9em; }
.wayhint-command { font-family: monospace; color: #a6e3a1; }
.wayhint-category { opacity: 0.6; font-size: 0.8em; }
.wayhint-detail { padding: 8px 12px; border-top: 1px solid alpha(#cdd6f4, 0.15); font-size: 0.9em; }
.wayhint-toolbar { padding: 6px 8px; border-top: 1px solid alpha(#cdd6f4, 0.15); }
.wayhint-toolbar button { padding: 2px 8px; }
.wayhint-chip { background-color: alpha(#89b4fa, 0.25); border-radius: 6px; padding: 1px 6px; }
.wayhint-form { padding: 8px 12px; border-top: 1px solid alpha(#cdd6f4, 0.15); }
.wayhint-form-title { font-weight: bold; padding-bottom: 4px; }
.wayhint-form-label { opacity: 0.7; font-size: 0.85em; }
.wayhint-form-note { color: #f9e2af; font-size: 0.85em; padding-top: 4px; }
.wayhint-help { padding: 4px 12px; opacity: 0.6; font-size: 0.8em; font-family: monospace; }
"""


def install(user_css: Path | None) -> None:
    display = Gdk.Display.get_default()
    if display is None:
        return
    base = Gtk.CssProvider()
    base.load_from_data(DEFAULT_CSS)
    Gtk.StyleContext.add_provider_for_display(
        display, base, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    if user_css is not None and user_css.is_file():
        user = Gtk.CssProvider()
        try:
            user.load_from_path(str(user_css))
        except Exception as e:  # GLib.Error; a bad stylesheet must not stop the daemon
            log.warning("style.css not loaded: %s", e)
            return
        Gtk.StyleContext.add_provider_for_display(display, user, Gtk.STYLE_PROVIDER_PRIORITY_USER)
