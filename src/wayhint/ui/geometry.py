"""Anchor name → layer-shell edges + margins, and px/% size resolution. No GTK imports."""

from __future__ import annotations

from dataclasses import dataclass

from wayhint.models import ANCHORS, DisplayConfig, Margin, OutputInfo, Size

# Which layer-shell edges each anchor name pins to.
_EDGES: dict[str, frozenset[str]] = {
    "top-left": frozenset({"top", "left"}),
    "top": frozenset({"top"}),
    "top-right": frozenset({"top", "right"}),
    "left": frozenset({"left"}),
    "center": frozenset(),
    "right": frozenset({"right"}),
    "bottom-left": frozenset({"bottom", "left"}),
    "bottom": frozenset({"bottom"}),
    "bottom-right": frozenset({"bottom", "right"}),
}
assert set(_EDGES) == set(ANCHORS)


@dataclass(frozen=True)
class Placement:
    edges: frozenset[str]  # subset of {"top","right","bottom","left"}
    margins: Margin  # only margins on anchored edges are meaningful
    width: int | None  # None → let GTK size naturally
    height: int | None


def resolve_size(size: Size | None, reference: int | None) -> int | None:
    if size is None:
        return None
    if size.unit == "%":
        if reference is None:
            return None  # unknown output → cannot resolve a percentage
        return max(1, size.to_px(reference))
    return max(1, size.to_px(0))


def placement(display: DisplayConfig, output: OutputInfo | None) -> Placement:
    anchor = display.anchor or "top-right"
    edges = _EDGES[anchor]
    margin = display.margin or Margin()
    ref_w = output.width if output else None
    ref_h = output.height if output else None
    width = resolve_size(display.width, ref_w)
    height = resolve_size(display.height, ref_h)
    # keep the window inside the output when both size and margins are known
    if output is not None:
        if width is not None:
            avail = (
                ref_w
                - (margin.left if "left" in edges else 0)
                - (margin.right if "right" in edges else 0)
            )
            width = max(1, min(width, avail))
        if height is not None:
            avail = (
                ref_h
                - (margin.top if "top" in edges else 0)
                - (margin.bottom if "bottom" in edges else 0)
            )
            height = max(1, min(height, avail))
    return Placement(edges=edges, margins=margin, width=width, height=height)
