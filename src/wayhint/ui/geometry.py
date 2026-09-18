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


# A hand-resized overlay must stay big enough to read and small enough to be an overlay.
MIN_WIDTH = 220
MIN_HEIGHT = 120


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


def resize_delta(
    start: tuple[int, int],
    dx: float,
    dy: float,
    edges: frozenset[str],
    output: OutputInfo | None,
) -> tuple[int, int]:
    """Size after dragging the grip by ``(dx, dy)`` from a window that was ``start`` big.

    The grip sits on the corner away from the anchored edges, so dragging *away* from the anchor
    is what makes the window bigger: anchored right means dragging left (negative ``dx``) grows
    it. On an unanchored axis the window is centred and grows both ways, so the edge only travels
    half of what the pointer does -- the sign is still the one that reads as "drag out to grow".
    """
    sx = -1 if "right" in edges else 1
    sy = -1 if "bottom" in edges else 1
    width = start[0] + round(sx * dx)
    height = start[1] + round(sy * dy)
    return (
        _clamp(width, MIN_WIDTH, output.width if output else None),
        _clamp(height, MIN_HEIGHT, output.height if output else None),
    )


def _clamp(value: int, low: int, high: int | None) -> int:
    if high is not None:
        value = min(value, max(low, high))
    return max(low, value)
