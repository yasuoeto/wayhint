"""The overlay window. Receives ``ResolvedContext`` + sheets + config; talks to nothing else.

Keyboard: the mode is ``normal`` / ``search`` / ``edit`` and the grab follows from it and from
visibility, in :meth:`_sync_keyboard_mode` and nowhere else (DESIGN 編集モード §1). ``normal`` is
NONE, so the app underneath keeps receiving input; ``search`` and ``edit`` are ON_DEMAND while the
overlay is visible. Hiding, or leaving the workspace, keeps the mode but drops the grab, so a
failed refocus can never leave the keyboard captured.

Decisions about *what* a key means live in :mod:`wayhint.ui.editmode` (pure, tested headless);
this module only turns them into widget changes and callbacks. Writing YAML is the daemon's job:
the form hands back a draft, never a document.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from wayhint import clipboard  # noqa: E402
from wayhint.config import GlobalConfig  # noqa: E402
from wayhint.i18n import Translator, translator  # noqa: E402
from wayhint.models import HINT_KINDS, Hint, HintSheet, ResolvedContext  # noqa: E402
from wayhint.selection import (  # noqa: E402
    search_hints,
    sheet_for_hint,
    sort_hints,
    visible_hints,
)
from wayhint.ui import editmode  # noqa: E402
from wayhint.ui.editmode import FormDraft, keyboard_grab  # noqa: E402
from wayhint.ui.geometry import Placement, placement, resize_delta  # noqa: E402
from wayhint.yaml_store import Issue  # noqa: E402

log = logging.getLogger(__name__)

GRIP_PX = 16  # the corner the pointer can grab to resize; layer surfaces have no frame
GRIP_EDGE_PX = 6  # the side strips next to it, for one axis at a time
KEY_MAX_CHARS = 12  # the key column wraps past this; `.wayhint-key` min-width keeps the floor

_EDGE = {
    "top": LayerShell.Edge.TOP,
    "right": LayerShell.Edge.RIGHT,
    "bottom": LayerShell.Edge.BOTTOM,
    "left": LayerShell.Edge.LEFT,
}


class _RowLayout(Gtk.BinLayout):
    """Lays the row out like a plain bin, then lets it re-check its vertical alignment.

    A widget that has a layout manager never gets its own ``size_allocate`` called, and the
    number of lines a label takes is only known once it has been laid out at the final width,
    so this is where :class:`HintRow` learns about a wrap.
    """

    def do_allocate(self, widget: Gtk.Widget, width: int, height: int, baseline: int) -> None:
        Gtk.BinLayout.do_allocate(self, widget, width, height, baseline)
        widget.sync_align()


class HintRow(Gtk.ListBoxRow):
    def __init__(self, hint: Hint, show_category: bool) -> None:
        super().__init__()
        self.hint = hint
        self.set_layout_manager(_RowLayout())
        self.add_css_class("wayhint-row")
        if hint.favorite:
            self.add_css_class("favorite")
        shown = editmode.display_fields(hint.kind)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        # A chord ("Ctrl-x Ctrl-s") is wider than the column, so wrap instead of letting the
        # label push the rest of the row off the fixed-width overlay. WORD_CHAR so that a long
        # key with no space in it breaks too. Newlines written in the YAML are kept as they are.
        # The vertical alignment of the key against the title is decided in sync_align(),
        # after Pango knows how many lines each of them takes.
        key = Gtk.Label(
            label=(hint.key or "") if "key" in shown else "",
            xalign=0,
            valign=Gtk.Align.BASELINE_CENTER,
            wrap=True,
            wrap_mode=Pango.WrapMode.WORD_CHAR,
            max_width_chars=KEY_MAX_CHARS,
        )
        key.add_css_class("wayhint-key")
        box.append(key)
        # baseline_child=0: the title, not the command line under it, carries the baseline.
        col = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            hexpand=True,
            valign=Gtk.Align.BASELINE_CENTER,
            baseline_child=0,
        )
        title = Gtk.Label(label=("★ " if hint.favorite else "") + hint.title, xalign=0, wrap=True)
        title.add_css_class("wayhint-title")
        col.append(title)
        self._key = key
        self._col = col
        self._title = title
        if hint.command and "command" in shown:
            cmd = Gtk.Label(label=hint.command, xalign=0, ellipsize=3, selectable=False)
            cmd.add_css_class("wayhint-command")
            col.append(cmd)
        box.append(col)
        if show_category and hint.category:
            cat = Gtk.Label(label=hint.category, xalign=1, valign=Gtk.Align.START)
            cat.add_css_class("wayhint-category")
            box.append(cat)
        self.set_child(box)

    def sync_align(self) -> None:
        """Keep the key and the title on one baseline, or centre them once one of them wraps.

        How many lines each label takes is only known after Pango has laid it out at the
        current width, so the choice is made from the allocation. While both are a single
        line BASELINE_CENTER puts the two fonts on a shared baseline; once one of them wraps,
        pinning the other to the first line looks detached, so both are centred instead.
        """
        wrapped = (
            self._key.get_layout().get_line_count() > 1
            or self._title.get_layout().get_line_count() > 1
        )
        align = Gtk.Align.CENTER if wrapped else Gtk.Align.BASELINE_CENTER
        if self._key.get_valign() == align:
            return
        # Not from inside the allocation: changing valign queues another one.
        GLib.idle_add(self._apply_align, align)

    def _apply_align(self, align: Gtk.Align) -> bool:
        self._key.set_valign(align)
        self._col.set_valign(align)
        return GLib.SOURCE_REMOVE


class HintWindow(Gtk.Window):
    def __init__(
        self,
        app: Gtk.Application,
        on_edit: Callable[[HintSheet | None, Hint | None], None],
        on_close: Callable[[], None],
        on_action: Callable[[str, dict | None], None],
        on_resize: Callable[[int, int], None],
        refocus: Callable[[str | None], None],
        tr: Translator | None = None,
    ) -> None:
        super().__init__(application=app, title="wayhint", decorated=False)
        self.add_css_class("wayhint")
        self._on_edit = on_edit
        self._on_close = on_close
        self._on_action = on_action
        self._on_resize = on_resize
        self._refocus = refocus
        self._tr = tr or translator()
        self._ctx: ResolvedContext | None = None
        self._sheets: dict[str, HintSheet] = {}
        self._config = GlobalConfig()
        self._hints: list[Hint] = []
        self._mode = "normal"
        self._form: FormDraft | None = None
        self._delete_pending: str | None = None
        self._filter: str | None = None
        self._completion: tuple[str, str] | None = None  # (typed prefix, candidate now shown)
        self._selected_id: str | None = None
        self._edges: frozenset[str] = frozenset({"top", "right"})  # set by _apply_placement
        self._drag_from: tuple[int, int] | None = None  # window size when the drag started

        LayerShell.init_for_window(self)
        LayerShell.set_namespace(self, "wayhint")
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_exclusive_zone(self, 0)
        self._sync_keyboard_mode()  # mode is 'normal' and nothing is visible yet, so NONE

        self._build()
        self.connect("close-request", self._on_close_request)
        key = Gtk.EventControllerKey()
        # CAPTURE: the overlay decides before GTK moves focus with Tab or the list eats Enter.
        key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)
        # BUBBLE: what a text field and its input method did not want. Enter and Esc only reach
        # here when no conversion was in flight, which is what makes the form usable with an IME.
        late = Gtk.EventControllerKey()
        late.connect("key-pressed", self._on_key_late)
        self.add_controller(late)

    # --- widgets ----------------------------------------------------------------------------

    def _build(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame = Gtk.Overlay(child=root)
        self.set_child(frame)
        # The side strips go down first so the corner, added last, wins where they meet.
        self._grips = {axis: self._build_grip(axis) for axis in ("x", "y", "both")}
        for grip in self._grips.values():
            frame.add_overlay(grip)
        self._header = Gtk.Label(xalign=0)
        self._header.add_css_class("wayhint-header")
        root.append(self._header)
        self._context_label = Gtk.Label(xalign=0, wrap=True)
        self._context_label.add_css_class("wayhint-context")
        root.append(self._context_label)
        self._error = Gtk.Label(xalign=0, wrap=True, visible=False, selectable=True)
        self._error.add_css_class("wayhint-error")
        root.append(self._error)
        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, visible=False)
        self._search_row = search_row
        self._search = Gtk.SearchEntry(hexpand=True, placeholder_text=self._tr("search hints…"))
        self._search.connect("search-changed", lambda *_: self._render_list())
        self._search.connect("stop-search", lambda *_: self.end_search())
        search_row.append(self._search)
        self._chip = Gtk.Label(visible=False)
        self._chip.add_css_class("wayhint-chip")
        search_row.append(self._chip)
        root.append(search_row)
        self._list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self._list.connect("row-selected", self._on_row_selected)
        scroller = Gtk.ScrolledWindow(vexpand=True, child=self._list)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        root.append(scroller)
        self._detail = Gtk.Label(xalign=0, wrap=True, selectable=True, visible=False)
        self._detail.add_css_class("wayhint-detail")
        root.append(self._detail)
        root.append(self._build_form())
        self._help = Gtk.Label(xalign=0, wrap=True, visible=False)
        self._help.add_css_class("wayhint-help")
        root.append(self._help)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.add_css_class("wayhint-toolbar")
        self._search_btn = self._button(bar, self._tr("Search"), self._toggle_search)
        self._copy_btn = self._button(bar, self._tr("Copy"), self._copy_selected)
        self._button(bar, self._tr("Edit in editor"), self._edit_in_editor)
        self._button(bar, self._tr("Edit"), lambda: self._on_action("enter-edit", None))
        self._button(bar, self._tr("Close"), lambda: self._on_close())
        root.append(bar)

    def _build_form(self) -> Gtk.Widget:
        """The quick-add / edit form. One column of labelled rows, narrow enough for 420px."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, visible=False)
        box.add_css_class("wayhint-form")
        self._form_box = box
        self._form_title = Gtk.Label(xalign=0)
        self._form_title.add_css_class("wayhint-form-title")
        box.append(self._form_title)
        self._entries: dict[str, Gtk.Entry] = {}
        self._rows: dict[str, Gtk.Box] = {}
        for name, label in (
            ("title", "Title"),
            ("key", "Key"),
            ("command", "Command"),
            ("category", "Category"),
            ("remark", "Remark"),
        ):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            caption = Gtk.Label(label=self._tr(label), xalign=0, width_chars=9)
            caption.add_css_class("wayhint-form-label")
            entry = Gtk.Entry(hexpand=True)
            # ``activate`` is Enter *after* the input method is done with it: a conversion being
            # confirmed does not emit it, so this is the IME-safe way to save (the bubble
            # controller never sees Enter, because the entry consumes it).
            entry.connect("activate", lambda *_: self._save_form())
            row.append(caption)
            row.append(entry)
            box.append(row)
            self._entries[name] = entry
            self._rows[name] = row

        kind_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        kind_row.append(Gtk.Label(label=self._tr("Kind"), xalign=0, width_chars=9))
        self._kind = Gtk.DropDown.new_from_strings(list(HINT_KINDS))
        self._kind.connect("notify::selected", lambda *_: self._sync_form_rows())
        kind_row.append(self._kind)
        box.append(kind_row)
        self._form_note = Gtk.Label(xalign=0, wrap=True, visible=False)
        self._form_note.add_css_class("wayhint-form-note")
        box.append(self._form_note)
        return box

    def _build_grip(self, axis: str) -> Gtk.Widget:
        """One resize handle. A layer surface gets no frame from the compositor, so the drag has
        to be handled here: the pointer works in every mode because it needs no keyboard grab.

        ``axis`` is ``x`` (the side strip that only changes the width), ``y`` (only the height)
        or ``both`` (the corner).
        """
        grip = Gtk.Box(can_focus=False)
        grip.add_css_class("wayhint-grip")
        grip.add_css_class(f"wayhint-grip-{axis}")
        grip.set_size_request(
            GRIP_PX if axis in ("x", "both") else GRIP_EDGE_PX,
            GRIP_PX if axis in ("y", "both") else GRIP_EDGE_PX,
        )
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update, axis)
        drag.connect("drag-end", self._on_drag_end, axis)
        grip.add_controller(drag)
        return grip

    # --- resize ------------------------------------------------------------------------------

    def _on_drag_begin(self, *_args) -> None:
        self._drag_from = (self.get_width(), self.get_height())

    def _drag_size(self, dx: float, dy: float, axis: str) -> tuple[int, int] | None:
        if self._drag_from is None:
            return None
        out = self._ctx.output if self._ctx else None
        # A side strip pins the axis it does not own, so the size only moves the way it looks.
        return resize_delta(
            self._drag_from, 0 if axis == "y" else dx, 0 if axis == "x" else dy, self._edges, out
        )

    def _on_drag_update(self, _gesture, dx: float, dy: float, axis: str) -> None:
        size = self._drag_size(dx, dy, axis)
        if size is not None:
            self.set_size_request(*size)

    def _on_drag_end(self, _gesture, dx: float, dy: float, axis: str) -> None:
        size = self._drag_size(dx, dy, axis)
        self._drag_from = None
        if size is None:
            return
        self.set_size_request(*size)
        self._on_resize(*size)  # the daemon writes config.yaml; the reload brings it back here

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
        # Coming back to a workspace re-takes the grab if the mode still wants it.
        self._sync_keyboard_mode()
        if self._mode == "edit":
            self._help.set_visible(True)
            self._help.set_label(self._help_text())

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

        The mode and any draft survive -- coming back to the workspace has to find the form as it
        was (0014 D4) -- but the grab does not.
        """
        self.set_visible(False)
        self._delete_pending = None
        self._sync_keyboard_mode()

    def is_shown(self) -> bool:
        return self.get_visible()

    @property
    def mode(self) -> str:
        return self._mode

    # --- modes and keyboard ----------------------------------------------------------------

    def _focus_soon(self, widget: Gtk.Widget) -> None:
        """Focus a widget that was just shown; retry once if it is not ready to take it yet."""
        if widget.grab_focus():
            return
        GLib.idle_add(lambda: (widget.grab_focus(), False)[1])

    def _sync_keyboard_mode(self) -> None:
        """The only place that touches ``keyboard_mode``. See the module docstring.

        EXCLUSIVE, not ON_DEMAND: with on-demand the compositor only hands the keyboard over on
        the *next* click on the surface, so pressing the Search button left the keys going to the
        application underneath. Search and edit are the modes where the overlay is being typed
        into, so taking the keyboard outright is what the user just asked for.
        """
        grab = keyboard_grab(self._mode, self.get_visible())
        log.debug("keyboard: mode=%s visible=%s grab=%s", self._mode, self.get_visible(), grab)
        LayerShell.set_keyboard_mode(
            self,
            LayerShell.KeyboardMode.EXCLUSIVE if grab else LayerShell.KeyboardMode.NONE,
        )

    def set_mode(self, mode: str, *, refocus: bool = True) -> None:
        """Switch mode and make the widgets and the grab agree with it."""
        if mode not in editmode.MODES:
            raise ValueError(f"unknown mode: {mode!r}")
        leaving = self._mode
        self._mode = mode
        self._delete_pending = None
        if mode != "search":
            self._search.set_text("")
            self._search_row.set_visible(False)
            self._search_btn.set_label(self._tr("Search"))
            self._filter = None
            self._completion = None
            self._chip.set_visible(False)
        if mode != "edit":
            self.close_form()
        self._help.set_visible(mode == "edit")
        if mode == "edit":
            self._help.set_label(self._help_text())
        self._sync_keyboard_mode()  # after the widgets, before anything can steal focus
        if mode == "search":
            self._search_row.set_visible(True)
            self._search_btn.set_label(self._tr("Done"))  # the same button ends the search
        self._render_list()  # restoring the selection can take the focus, so grab it after
        if mode == "search":
            self._focus_soon(self._search)
        if mode == "normal" and leaving != "normal" and refocus:
            try:
                self._refocus(self._ctx.view_ref if self._ctx else None)
            except Exception:
                log.exception("refocus failed")

    def begin_search(self) -> None:
        self.set_mode("search")

    def end_search(self, refocus: bool = True) -> None:
        self.set_mode("normal", refocus=refocus)

    def _toggle_search(self) -> None:
        self.set_mode("normal" if self._mode == "search" else "search")

    def _help_text(self) -> str:
        if self._form is not None:
            return self._tr("Enter save · Esc discard · Tab next field · Ctrl+P parent sheet")
        return self._tr(
            "a add · Enter edit · dd delete · u undo · f favorite · J/K move · Esc leave"
        )

    def _on_key(self, _ctrl, keyval, _keycode, state) -> bool:
        name = Gdk.keyval_name(keyval) or ""
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if self._mode == "search":
            return self._search_key(name)
        if self._mode == "edit":
            return self._edit_key(name, ctrl)
        return False  # normal: the compositor does not even send us keys

    def _search_key(self, name: str) -> bool:
        # Escape is left to the entry's ``stop-search``: an input method needs it first, to cancel
        # a conversion rather than the whole search.
        if name in ("Tab", "ISO_Left_Tab"):
            self._cycle_filter(forward=name == "Tab")
            return True
        return False

    def _on_key_late(self, _ctrl, keyval, _keycode, state) -> bool:
        """Bubble phase: only runs when the focused widget and its IME let the key through."""
        if self._mode == "normal" or not self._editable_focused():
            return False
        name = Gdk.keyval_name(keyval) or ""
        if self._mode == "search":
            if name == "Escape":
                self.end_search()
                return True
            return False
        action = editmode.edit_action(
            name, ctrl=bool(state & Gdk.ModifierType.CONTROL_MASK), editable=True
        )
        if action == editmode.FORM_SAVE:
            self._save_form()
            return True
        if action == editmode.FORM_CANCEL:
            self.close_form()
            return True
        return False

    def _edit_key(self, name: str, ctrl: bool) -> bool:
        editable = self._editable_focused()
        # With the form open, Enter and Esc mean save and discard wherever the focus sits -- the
        # kind dropdown is not an Editable, and Enter there must not re-open a form.
        action = editmode.edit_action(
            name,
            ctrl=ctrl,
            editable=editable or self._form is not None,
            pending=bool(self._delete_pending),
        )
        if editable and not editmode.capture_in_editable(action):
            return False  # let the input method have it; :meth:`_on_key_late` picks up the rest
        if editmode.cancels_delete(action) and self._delete_pending is not None:
            self._delete_pending = None
            self._error.set_visible(False)
        if action is None:
            return False
        if action == editmode.FORM_NEXT or action == editmode.FORM_PREVIOUS:
            self._move_focus(forward=action == editmode.FORM_NEXT)
            return True
        if action == editmode.FORM_SAVE:
            self._save_form()
            return True
        if action == editmode.FORM_CANCEL:
            self.close_form()
            self._help.set_label(self._help_text())
            return True
        if action == editmode.DELETE_CONFIRM:
            hint = self._selected()
            if hint is None:
                self.show_message(f"⚠ {self._tr('no hint selected')}")
                return True
            self._delete_pending = hint.id
            self.show_message(self._tr("press d again to delete {title}").format(title=hint.title))
            return True
        payload = self._action_payload(action)
        if payload is None:
            return True
        self._on_action(action, payload)
        return True

    def _action_payload(self, action: str) -> dict | None:
        """Everything the daemon needs to act, taken from the selection (never from the file)."""
        if action in (editmode.UNDO, editmode.EXIT_EDIT, editmode.ADD, editmode.FORM_PARENT):
            return {}
        hint = self._selected()
        if hint is None:
            self.show_message(f"⚠ {self._tr('no hint selected')}")
            return None
        return {"hint_id": hint.id, "file": str(hint.location.file)}

    def _editable_focused(self) -> bool:
        return isinstance(self.get_focus(), Gtk.Editable)

    def _move_focus(self, forward: bool) -> None:
        direction = Gtk.DirectionType.TAB_FORWARD if forward else Gtk.DirectionType.TAB_BACKWARD
        self.child_focus(direction)

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
        self._edges = place.edges
        self._place_grip(place.edges)
        monitor = self._find_monitor(out.name) if out else None
        LayerShell.set_monitor(self, monitor)

    def _place_grip(self, edges: frozenset[str]) -> None:
        """Opposite the anchored edges: that is the side the window grows towards.

        The corner takes both axes; the two side strips run along the same free edges and take
        one each.
        """
        right = "right" in edges
        bottom = "bottom" in edges
        near_x = Gtk.Align.START if right else Gtk.Align.END  # the free vertical edge
        near_y = Gtk.Align.START if bottom else Gtk.Align.END  # the free horizontal edge
        corner = "nesw-resize" if right != bottom else "nwse-resize"
        for axis, halign, valign, cursor in (
            ("x", near_x, Gtk.Align.FILL, "ew-resize"),
            ("y", Gtk.Align.FILL, near_y, "ns-resize"),
            ("both", near_x, near_y, corner),
        ):
            grip = self._grips[axis]
            grip.set_halign(halign)
            grip.set_valign(valign)
            grip.set_cursor(Gdk.Cursor.new_from_name(cursor, None))

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
        previous_index = self._selected_index()
        hints = sort_hints(
            visible_hints(self._active_sheet(), self._parent_sheet(), self._config.parent_tags)
        )
        if self._mode == "search":
            query = editmode.parse_search(self._search.get_text())
            if query.filtering and query.partial is None:
                self._filter = query.category
            if self._filter:
                hints = [h for h in hints if editmode.matches_category(h, self._filter)]
            if query.text:
                hints = search_hints(hints, query.text)
            hints = hints[: self._config.max_results]
            self._show_chip()
        self._hints = hints
        self._list.remove_all()
        for h in hints:
            self._list.append(HintRow(h, self._config.show_category))
        self._detail.set_visible(False)
        self._copy_btn.set_sensitive(False)
        self._restore_selection(previous_index)

    def _selected_index(self) -> int | None:
        row = self._list.get_selected_row()
        return row.get_index() if row is not None else None

    def _restore_selection(self, previous_index: int | None) -> None:
        """After a re-render keep the same hint selected, or failing that the same row (D2)."""
        index = editmode.restore_index(
            [h.id for h in self._hints], self._selected_id, previous_index
        )
        if index is None:
            return
        row = self._list.get_row_at_index(index)
        if row is not None:
            self._list.select_row(row)

    def _category_order(self) -> list[str | None]:
        return editmode.category_order(
            sort_hints(
                visible_hints(self._active_sheet(), self._parent_sheet(), self._config.parent_tags)
            )
        )

    def _cycle_filter(self, forward: bool) -> None:
        """Tab in the search box: cycle the candidates for a half-typed ``#name``, else the filter.

        Pressing Tab again on a name this method completed keeps the prefix that was typed, so
        ``#s`` reaches both ``screen`` and ``session``. Touching the text any other way starts over.
        """
        text = self._search.get_text()
        query = editmode.parse_search(text)
        order = self._category_order()
        # Continuing a completion: the box still holds exactly what the last Tab put there.
        continuing = self._completion is not None and text == f"#{self._completion[1]} "
        prefix, current = self._completion if continuing else (query.partial, None)
        if prefix is not None:
            match = editmode.next_completion(prefix, order, current, forward)
            if match is not None:
                self._completion = (prefix, match)
                self._search.set_text(f"#{match} ")
                self._search.set_position(-1)
                self._filter = match
                self._render_list()
                return
        self._completion = None
        self._filter = editmode.cycle_category(order, self._filter, forward)
        self._render_list()

    def _show_chip(self) -> None:
        if not self._filter:
            self._chip.set_visible(False)
            return
        label = self._tr("inbox") if self._filter == editmode.PSEUDO_CATEGORY else self._filter
        self._chip.set_label(self._tr("filter: {category}").format(category=label))
        self._chip.set_visible(True)

    # --- form --------------------------------------------------------------------------------

    def open_form(self, draft: FormDraft) -> None:
        """Show the form for ``draft``: quick add when it has no ``hint_id``, else an edit."""
        self._form = draft
        self._form_title.set_label(
            self._tr("New hint")
            if draft.hint_id is None
            else f"{self._tr('Edit')}: {draft.hint_id}"
        )
        for name, entry in self._entries.items():
            entry.set_text(draft.value(name))
        kind = draft.value("kind") or "shortcut"
        self._kind.set_selected(HINT_KINDS.index(kind) if kind in HINT_KINDS else 0)
        self._sync_form_rows()
        self._form_note.set_visible(bool(draft.warning))
        if draft.warning:
            self._form_note.set_label(f"⚠ {self._tr(draft.warning)}")
        self._form_box.set_visible(True)
        self._help.set_label(self._help_text())
        self._focus_soon(self._entries["title"])

    def close_form(self) -> None:
        self._form = None
        self._form_box.set_visible(False)
        self._form_note.set_visible(False)
        if self._mode == "edit":
            self._help.set_label(self._help_text())
            self._list.grab_focus()

    def show_form_error(self, text: str | None) -> None:
        """A problem with *this* form, shown inside it (a broken target sheet, for instance)."""
        self._form_note.set_label(f"⚠ {text}" if text else "")
        self._form_note.set_visible(bool(text))

    def form_draft(self) -> FormDraft | None:
        """The draft with the widgets' current values, for the daemon to keep across a hide."""
        if self._form is None:
            return None
        self._form.fields = {name: e.get_text() for name, e in self._entries.items()}
        self._form.fields["kind"] = self._current_kind()
        return self._form

    def _current_kind(self) -> str:
        index = self._kind.get_selected()
        return HINT_KINDS[index] if 0 <= index < len(HINT_KINDS) else "shortcut"

    def _sync_form_rows(self) -> None:
        wanted = editmode.kind_fields(self._current_kind())
        for name in ("key", "command"):
            self._rows[name].set_visible(name in wanted)

    def _save_form(self) -> None:
        draft = self.form_draft()
        if draft is None:
            return
        if not draft.value("title").strip():
            self.show_message(f"⚠ {self._tr('title is required')}")
            self._entries["title"].grab_focus()
            return
        self._on_action(editmode.FORM_SAVE, {"draft": draft})

    def toggle_form_parent(self) -> None:
        if self._form is not None and self._form.hint_id is None:
            self._form.to_parent = not self._form.to_parent
            self._form_title.set_label(
                f"{self._tr('New hint')}"
                + (f" ({self._tr('to parent sheet')})" if self._form.to_parent else "")
            )

    def _selected(self) -> Hint | None:
        row = self._list.get_selected_row()
        return row.hint if isinstance(row, HintRow) else None

    def _on_row_selected(self, _list, row) -> None:
        hint = row.hint if isinstance(row, HintRow) else None
        self._selected_id = hint.id if hint is not None else self._selected_id
        if self._delete_pending is not None and (hint is None or hint.id != self._delete_pending):
            self._delete_pending = None  # moving the selection calls off a pending delete
        if hint is None:
            self._detail.set_visible(False)
            self._copy_btn.set_sensitive(False)
            return
        # Only what the row cannot show. `kind` and `id` are for whoever edits the YAML (id is
        # the duplicate check and the `{hint_id}` placeholder), not for whoever reads the hint.
        lines: list[str] = []
        if hint.remark:
            lines.append(hint.remark)
        if hint.tags:
            lines.append(f"{self._tr('tags')}: " + ", ".join(hint.tags))
        if hint.source:
            lines.append(f"{self._tr('source')}: {hint.source}")
        if hint.learned:
            lines.append(f"{self._tr('learned')}: {hint.learned}")
        self._detail.set_label("\n".join(lines))
        self._detail.set_visible(bool(lines))
        self._copy_btn.set_sensitive(hint.copy_text() is not None)

    def _copy_selected(self) -> None:
        hint = self._selected()
        text = hint.copy_text() if hint else None
        if text is not None:
            clipboard.copy_text(text)

    def _edit_in_editor(self) -> None:
        """Open the file the selected hint lives in, at its line.

        With nothing selected it is the sheet on display, from the top. The editor is for
        curating a whole sheet now that single hints are edited in place (DECISIONS 0017), so
        one button covers both: ``edit_target`` lets the hint's own location win over the sheet.
        """
        hint = self._selected()
        sheet = sheet_for_hint(self._sheets.values(), hint) or self._active_sheet()
        self._on_edit(sheet, hint)
