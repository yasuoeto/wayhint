"""The overlay window. Receives ``ResolvedContext`` + sheets + config; talks to nothing else.

Keyboard: ``keyboard_mode`` is NONE while hints are shown, so the app underneath keeps
receiving input. Only :meth:`begin_search` switches to ON_DEMAND; :meth:`end_search` always
switches back to NONE before trying to hand focus to the previous view (the ``refocus``
callback), so a failed refocus can never leave a keyboard grab behind.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from wayhint import clipboard  # noqa: E402
from wayhint.config import GlobalConfig  # noqa: E402
from wayhint.i18n import Translator, translator  # noqa: E402
from wayhint.models import Hint, HintSheet, ResolvedContext  # noqa: E402
from wayhint.selection import search_hints, sort_hints, visible_hints  # noqa: E402
from wayhint.ui.geometry import Placement, placement  # noqa: E402
from wayhint.yaml_store import Issue  # noqa: E402

log = logging.getLogger(__name__)

_EDGE = {
    "top": LayerShell.Edge.TOP,
    "right": LayerShell.Edge.RIGHT,
    "bottom": LayerShell.Edge.BOTTOM,
    "left": LayerShell.Edge.LEFT,
}


class HintRow(Gtk.ListBoxRow):
    def __init__(self, hint: Hint, show_category: bool) -> None:
        super().__init__()
        self.hint = hint
        self.add_css_class("wayhint-row")
        if hint.favorite:
            self.add_css_class("favorite")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        key = Gtk.Label(label=hint.key or "", xalign=0)
        key.add_css_class("wayhint-key")
        box.append(key)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        title = Gtk.Label(label=("★ " if hint.favorite else "") + hint.title, xalign=0, wrap=True)
        title.add_css_class("wayhint-title")
        col.append(title)
        if hint.command:
            cmd = Gtk.Label(label=hint.command, xalign=0, ellipsize=3, selectable=False)
            cmd.add_css_class("wayhint-command")
            col.append(cmd)
        box.append(col)
        if show_category and hint.category:
            cat = Gtk.Label(label=hint.category, xalign=1, valign=Gtk.Align.START)
            cat.add_css_class("wayhint-category")
            box.append(cat)
        self.set_child(box)


class HintWindow(Gtk.Window):
    def __init__(
        self,
        app: Gtk.Application,
        on_refresh: Callable[[], None],
        on_edit: Callable[[HintSheet | None, Hint | None], None],
        on_close: Callable[[], None],
        refocus: Callable[[str | None], None],
        tr: Translator | None = None,
    ) -> None:
        super().__init__(application=app, title="wayhint", decorated=False)
        self.add_css_class("wayhint")
        self._on_refresh = on_refresh
        self._on_edit = on_edit
        self._on_close = on_close
        self._refocus = refocus
        self._tr = tr or translator()
        self._ctx: ResolvedContext | None = None
        self._sheets: dict[str, HintSheet] = {}
        self._config = GlobalConfig()
        self._hints: list[Hint] = []
        self._searching = False

        LayerShell.init_for_window(self)
        LayerShell.set_namespace(self, "wayhint")
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_exclusive_zone(self, 0)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.NONE)

        self._build()
        self.connect("close-request", self._on_close_request)
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

    # --- widgets ----------------------------------------------------------------------------

    def _build(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(root)
        self._header = Gtk.Label(xalign=0)
        self._header.add_css_class("wayhint-header")
        root.append(self._header)
        self._context_label = Gtk.Label(xalign=0, wrap=True)
        self._context_label.add_css_class("wayhint-context")
        root.append(self._context_label)
        self._error = Gtk.Label(xalign=0, wrap=True, visible=False, selectable=True)
        self._error.add_css_class("wayhint-error")
        root.append(self._error)
        self._search = Gtk.SearchEntry(visible=False, placeholder_text=self._tr("search hints…"))
        self._search.connect("search-changed", lambda *_: self._render_list())
        self._search.connect("stop-search", lambda *_: self.end_search())
        root.append(self._search)
        self._list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self._list.connect("row-selected", self._on_row_selected)
        scroller = Gtk.ScrolledWindow(vexpand=True, child=self._list)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        root.append(scroller)
        self._detail = Gtk.Label(xalign=0, wrap=True, selectable=True, visible=False)
        self._detail.add_css_class("wayhint-detail")
        root.append(self._detail)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.add_css_class("wayhint-toolbar")
        self._search_btn = self._button(bar, self._tr("Search"), self._toggle_search)
        self._button(bar, self._tr("Refresh"), lambda: self._on_refresh())
        self._copy_btn = self._button(bar, self._tr("Copy"), self._copy_selected)
        self._edit_hint_btn = self._button(bar, self._tr("Edit hint"), self._edit_selected)
        self._button(bar, self._tr("Edit sheet"), lambda: self._on_edit(self._active_sheet(), None))
        self._button(bar, self._tr("Close"), lambda: self._on_close())
        root.append(bar)

    @staticmethod
    def _button(parent: Gtk.Box, label: str, cb: Callable[[], None]) -> Gtk.Button:
        b = Gtk.Button(label=label)
        b.connect("clicked", lambda *_: cb())
        parent.append(b)
        return b

    # --- public API used by the daemon -----------------------------------------------------

    @property
    def context(self) -> ResolvedContext | None:
        return self._ctx

    def present_context(
        self, ctx: ResolvedContext, sheets: Sequence[HintSheet], config: GlobalConfig
    ) -> None:
        self._ctx = ctx
        self._sheets = {s.id: s for s in sheets}
        self._config = config
        self._apply_placement()
        self._render_header()
        self._render_list()
        self.set_visible(True)
        self.present()

    def show_issues(self, issues: Sequence[Issue]) -> None:
        """YAML errors from the store; shown above the list, hints stay (last-known-good)."""
        if issues:
            lines = [f"⚠ {self._tr('YAML error')}: {i}" for i in issues[:3]]
            if len(issues) > 3:
                lines.append(self._tr("… and {n} more").format(n=len(issues) - 3))
            self._error.set_label("\n".join(lines))
            self._error.set_visible(True)
        elif not (self._ctx and self._ctx.error):
            self._error.set_visible(False)

    def show_message(self, text: str) -> None:
        self._error.set_label(text)
        self._error.set_visible(True)

    def hide_overlay(self) -> None:
        """Put the surface away without deciding anything: the daemon owns "is it open here?".

        Closing on the user's behalf goes through the ``on_close`` callback instead, so the
        workspace stops counting the overlay as open on it.
        """
        if self._searching:
            self.end_search(refocus=False)
        self.set_visible(False)

    def is_shown(self) -> bool:
        return self.get_visible()

    # --- search / keyboard -----------------------------------------------------------------

    def begin_search(self) -> None:
        self._searching = True
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.ON_DEMAND)
        self._search.set_visible(True)
        self._search_btn.set_label(self._tr("Done"))
        self._search.grab_focus()

    def end_search(self, refocus: bool = True) -> None:
        # Order matters: drop the grab first, no matter what refocus does afterwards.
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.NONE)
        self._searching = False
        self._search.set_text("")
        self._search.set_visible(False)
        self._search_btn.set_label(self._tr("Search"))
        self._render_list()
        if refocus:
            try:
                self._refocus(self._ctx.view_ref if self._ctx else None)
            except Exception:
                log.exception("refocus failed")

    def _toggle_search(self) -> None:
        if self._searching:
            self.end_search()
        else:
            self.begin_search()

    def _on_key(self, _ctrl, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_Escape and self._searching:
            self.end_search()
            return True
        return False

    def _on_close_request(self, *_):
        self._on_close()
        return True  # keep the window object alive

    # --- rendering -------------------------------------------------------------------------

    def _active_sheet(self) -> HintSheet | None:
        if self._ctx is None or self._ctx.active_sheet is None:
            return None
        return self._sheets.get(self._ctx.active_sheet)

    def _parent_sheet(self) -> HintSheet | None:
        if self._ctx is None or self._ctx.parent_context is None:
            return None
        return self._sheets.get(self._ctx.parent_context)

    def _apply_placement(self) -> None:
        active = self._active_sheet()
        display = self._config.display
        if active is not None:
            display = active.display.merged_over(display)
        out = self._ctx.output if self._ctx else None
        place: Placement = placement(display, out)
        for name, edge in _EDGE.items():
            on = name in place.edges
            LayerShell.set_anchor(self, edge, on)
            LayerShell.set_margin(self, edge, getattr(place.margins, name) if on else 0)
        self.set_default_size(place.width or -1, place.height or -1)
        if place.width:
            self.set_size_request(place.width, place.height or -1)
        monitor = self._find_monitor(out.name) if out else None
        LayerShell.set_monitor(self, monitor)

    @staticmethod
    def _find_monitor(name: str) -> Gdk.Monitor | None:
        display = Gdk.Display.get_default()
        if display is None:
            return None
        monitors = display.get_monitors()
        for i in range(monitors.get_n_items()):
            m = monitors.get_item(i)
            if m.get_connector() == name:
                return m
        return None

    def _render_header(self) -> None:
        ctx = self._ctx
        active = self._active_sheet()
        parent = self._parent_sheet()
        title = active.title if active else "wayhint"
        if parent is not None and active is not parent:
            title = f"{parent.title} › {title}"
        self._header.set_label(title)
        parts = []
        if ctx and ctx.desktop_app:
            parts.append(ctx.desktop_app)
        if ctx and ctx.foreground_process:
            parts.append(ctx.foreground_process.name)
        if ctx and ctx.output:
            parts.append(ctx.output.name)
        if ctx and active is None and not ctx.error:
            parts.append(self._tr("no matching sheet"))
        self._context_label.set_label("  ·  ".join(parts))
        if ctx and ctx.error:
            self.show_message(f"⚠ {ctx.error}")
        else:
            self._error.set_visible(False)

    def _render_list(self) -> None:
        hints = sort_hints(
            visible_hints(self._active_sheet(), self._parent_sheet(), self._config.parent_tags)
        )
        if self._searching:
            hints = search_hints(hints, self._search.get_text())[: self._config.max_results]
        self._hints = hints
        self._list.remove_all()
        for h in hints:
            self._list.append(HintRow(h, self._config.show_category))
        self._detail.set_visible(False)
        self._copy_btn.set_sensitive(False)
        self._edit_hint_btn.set_sensitive(False)

    def _selected(self) -> Hint | None:
        row = self._list.get_selected_row()
        return row.hint if isinstance(row, HintRow) else None

    def _on_row_selected(self, _list, row) -> None:
        hint = row.hint if isinstance(row, HintRow) else None
        if hint is None:
            self._detail.set_visible(False)
            self._copy_btn.set_sensitive(False)
            self._edit_hint_btn.set_sensitive(False)
            return
        lines = [f"{hint.kind}  ·  {hint.id}"]
        if hint.remark:
            lines.append(hint.remark)
        if hint.tags:
            lines.append(f"{self._tr('tags')}: " + ", ".join(hint.tags))
        if hint.source:
            lines.append(f"{self._tr('source')}: {hint.source}")
        if hint.learned:
            lines.append(f"{self._tr('learned')}: {hint.learned}")
        self._detail.set_label("\n".join(lines))
        self._detail.set_visible(True)
        self._copy_btn.set_sensitive(hint.copy_text() is not None)
        self._edit_hint_btn.set_sensitive(True)

    def _copy_selected(self) -> None:
        hint = self._selected()
        text = hint.copy_text() if hint else None
        if text is not None:
            clipboard.copy_text(text)

    def _edit_selected(self) -> None:
        hint = self._selected()
        if hint is not None:
            self._on_edit(self._active_sheet(), hint)
