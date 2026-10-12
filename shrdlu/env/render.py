"""Drawing a scene, so a vision model has something to look at.

The image is the *only* thing a vision testee is shown, so it has to be
information-complete: everything the question bank can ask about must be
visible in it.  Four rules follow, and they are not stylistic preferences:

1. **An isometric table.**  The scene is a plane with two axes, so it is drawn
   as a plane: a diamond, with ``x`` running down-right and ``y`` down-left.
   An earlier version laid cells out straight down the page, which left objects
   hanging in the air above a strip of "table".

2. **The id is drawn on the object, and the id is what a testee answers with.**
   There is one identifier space; a testee never has to invent a name.  Ids are
   short and opaque (``a``, ``b``, ...) — a descriptive id like ``green-cube``
   would print the answer to "what colour is it?" on the object itself.

3. **Draw order is by depth, then by height within a stack.**  Getting this
   wrong is invisible in the data and glaring in the picture: the wrong order
   paints a supporting block over the block stacked on top of it.

4. **Labels are placed last and never left on top of each other**, and nothing
   may fall outside the finished picture.  The canvas is fitted to the result
   rather than guessed.  A label's line must also *reach* the object it names:
   the end point is found by aiming at that object's own outline, never by
   assuming it is a rectangle.

Output is SVG (text, no dependency, opens in any browser).  A PNG backend is
available when Pillow is installed, which is what most vision models want.

:func:`read_back` is the completeness check: it reconstructs the state from the
drawn geometry, so a round trip that comes out equal means the picture really
does carry the state.  It is a plain decoder, not a vision model — it proves the
image is sufficient, not that a particular model can read it.
"""

from __future__ import annotations

import io
import math
import os
from dataclasses import dataclass, field
from xml.sax.saxutils import escape as _xml
from typing import Dict, List, Optional, Sequence, Tuple

from ..world import Obj, World


class RenderError(Exception):
    """Raised when a picture cannot be produced."""


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

TILE_W = 132.0        # screen width of one table cell
TILE_H = 66.0         # screen height of one table cell (2:1 isometric)
MARGIN = 76.0
GRID_SLACK = 0.85     # how far the table extends past the outermost objects

WIDTH = {"big": 78.0, "small": 50.0}
HEIGHT = {"big": 54.0, "small": 34.0}

LABEL_W = 30.0
LABEL_H = 22.0
LEADER = 12.0
MIN_SHAPE = 20.0

PALETTE: Dict[str, str] = {
    "red": "#d64545",
    "green": "#3fa34d",
    "blue": "#3b6fd4",
    "yellow": "#e3b505",
    "white": "#f2f2f2",
    "black": "#3a3a3a",
    "brown": "#8a5a2b",
    "orange": "#e08b2e",
    "purple": "#8e5bd0",
    "grey": "#9aa0a6",
    "pink": "#e07a9a",
    "cyan": "#35b8c4",
    "magenta": "#c038a8",
}
FALLBACK_COLOUR = "#b0b0b0"
TABLE_FILL = "#f6f1e7"
TABLE_EDGE = "#cabfa8"
PAD_FILL = "#eef2f6"
PAD_EDGE = "#9fb3c8"
LABEL_FILL = "#ffffff"
LABEL_EDGE = "#333333"
LABEL_TEXT = "#111111"
LINK_COLOUR = "#7a7a7a"


def colour_of(name: str) -> str:
    return PALETTE.get(name, FALLBACK_COLOUR)


def _shade(hex_colour: str, factor: float) -> str:
    hex_colour = hex_colour.lstrip("#")
    parts = [int(hex_colour[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(
        "%02x" % max(0, min(255, int(round(value * factor)))) for value in parts
    )


def project(gx: float, gy: float) -> Tuple[float, float]:
    """Logical grid coordinates to the page, isometrically."""
    return (gx - gy) * TILE_W / 2.0, (gx + gy) * TILE_H / 2.0


# --------------------------------------------------------------------------
# The drawing plan
# --------------------------------------------------------------------------


@dataclass
class Shape:
    """One object as drawn.

    ``base_y`` and ``roof_y`` are where its underside and its top face were
    drawn.  They are *positions*, not relations: whether one object rests on
    another is left for :func:`read_back` to work out by comparing them.
    """

    ident: str
    kind: str
    color: str
    size: str
    cx: float
    base_y: float
    roof_y: float
    width: float
    height: float
    level: int = 0
    depth: float = 0.0
    held: bool = False
    holds: int = 0
    label_x: float = 0.0
    label_y: float = 0.0
    label_side: str = "above"      # above | below | left | right

    @property
    def label_above(self) -> bool:
        return self.label_side == "above"

    @property
    def half(self) -> float:
        return self.width / 2.0

    @property
    def dep(self) -> float:
        """Isometric depth offset: a quarter of the width, for a 2:1 look."""
        return self.width / 4.0

    @property
    def x(self) -> float:
        return self.cx - self.half

    @property
    def radius(self) -> float:
        """A ball's radius; also how far it reaches above its base."""
        return min(self.half, self.height / 2.0)

    @property
    def top(self) -> float:
        """The highest point that is actually **drawn**.

        This is not ``roof_y`` for every shape, and getting it wrong is
        invisible in the data but glaring in the picture:

        * a cuboid's top face is a rhombus, so its highest drawn point is the
          north vertex, ``roof_y - dep``;
        * a pyramid has no top face at all — its highest point is the apex,
          which sits at ``roof_y``.  Subtracting ``dep`` there left the end of
          every ``above`` leader floating in mid-air above the apex;
        * a ball is a circle standing on its base, so its highest point is
          ``base_y - 2r``.
        """
        if self.kind == "pyramid":
            return self.roof_y
        if self.kind == "ball":
            return self.base_y - 2.0 * self.radius
        return self.roof_y - self.dep

    @property
    def bottom(self) -> float:
        return self.base_y + self.dep

    def move(self, dx: float, dy: float) -> None:
        self.cx += dx
        self.base_y += dy
        self.roof_y += dy
        self.label_x += dx
        self.label_y += dy


@dataclass
class RenderPlan:
    """Everything needed to draw, and to check that the drawing is complete."""

    shapes: List[Shape] = field(default_factory=list)
    table: List[Tuple[float, float]] = field(default_factory=list)
    hand_pad: Optional[Tuple[float, float, float, float]] = None
    hand_caption: str = "in hand"
    width: float = 0.0
    height: float = 0.0

    def shape_for(self, ident: str) -> Optional[Shape]:
        for shape in self.shapes:
            if shape.ident == ident:
                return shape
        return None

    def draw_order(self) -> List[Shape]:
        """Far cells first, and within a stack the bottom-most first."""
        return sorted(self.shapes, key=lambda s: (s.depth, s.level))


#: What a picture cannot say: an object in the hand is drawn on a pad beside the
#: table, which is not a position on the table and reads back poorly.
UNCOVERED = ("hand",)

class CoverageError(Exception):
    """A scene whose picture would not carry the whole initial state."""


def uncovered(world: World) -> List[str]:
    """Why this world cannot be shown as one picture; empty means it can.

    The picture carries ids, shapes, colours, sizes and what rests on what.  It
    does not carry a held object, so a scene holding one has to be refused
    rather than drawn with a hole in it.
    """
    return ["%s is in hand" % o.ident for o in world.actual_objects()
            if world.pos_of(o)[0] == "hand"]


def require_covered(world: World) -> None:
    """Refuse a world whose picture would not carry the whole initial state."""
    reasons = uncovered(world)
    if reasons:
        raise CoverageError(
            "this scene cannot be shown as a picture: %s" % "; ".join(reasons))


def columns(world: World) -> List[List[Obj]]:
    """The scene as columns: each is a stack of objects, bottom first.

    The world does not say which column stands where — it only says what rests
    on what — so the layout is the drawing's own business.  Laying it out here
    instead of reading it from the state keeps the two from ever disagreeing,
    and it means a state recovered from a picture (which names no columns) can
    be drawn without inventing anything.
    """
    placed = [o for o in world.actual_objects()
              if o.support is None and not o.held]
    return [world.chain(root) for root in placed]


def _layout(index: int) -> Tuple[float, float]:
    """Where the ``index``-th column stands, in logical grid units."""
    return float(3 * (index % 3)), float(3 * (index // 3))


def plan(world: World, labels: bool = True) -> RenderPlan:
    render = RenderPlan()
    held: List[Obj] = []
    for obj in world.actual_objects():
        if world.pos_of(obj)[0] == "hand":
            held.append(obj)

    cells: Dict[Tuple[float, float], List[Obj]] = {}
    for index, column in enumerate(columns(world)):
        gx, gy = _layout(index)
        cells[(gx, gy)] = column
        cx, base = project(gx, gy)
        for level, obj in enumerate(column):
            height = HEIGHT.get(obj.size, 34.0)
            roof = base - height
            render.shapes.append(Shape(
                ident=obj.ident, kind=obj.kind, color=obj.color, size=obj.size,
                cx=cx, base_y=base, roof_y=roof,
                width=WIDTH.get(obj.size, 50.0), height=height,
                level=level, depth=gx + gy))
            base = roof

    render.table = _table_outline(cells)

    if held:
        render.hand_pad = _hand_pad(render, held)

    if labels:
        _place_labels(render)
    _fit_canvas(render, labels)
    return render


def _table_outline(cells: Dict[Tuple[float, float], List[Obj]]) -> List[Tuple[float, float]]:
    """The table top: a diamond covering every column, plus a little slack."""
    if not cells:
        return []
    gxs = [gx for gx, _ in cells]
    gys = [gy for _, gy in cells]
    lo_x, hi_x = min(gxs) - GRID_SLACK, max(gxs) + GRID_SLACK
    lo_y, hi_y = min(gys) - GRID_SLACK, max(gys) + GRID_SLACK
    return [project(lo_x, lo_y), project(hi_x, lo_y),
            project(hi_x, hi_y), project(lo_x, hi_y)]


def _hand_pad(render: RenderPlan, held: Sequence[Obj]) -> Tuple[float, float, float, float]:
    """A pad beside the table where a held object is shown."""
    xs = [p[0] for p in render.table] or [0.0]
    ys = [p[1] for p in render.table] or [0.0]
    left, top, bottom = min(xs), min(ys), max(ys)
    width = max(WIDTH.get(o.size, 50.0) for o in held) + 56.0
    pad_x = left - width - 40.0
    pad_y = (top + bottom) / 2.0 - 50.0
    ground = pad_y + 96.0
    for index, obj in enumerate(sorted(held, key=lambda o: o.ident)):
        height = HEIGHT.get(obj.size, 34.0)
        render.shapes.append(Shape(
            ident=obj.ident, kind=obj.kind, color=obj.color, size=obj.size,
            cx=pad_x + width / 2.0, base_y=ground - index * height,
            roof_y=ground - index * height - height,
            width=WIDTH.get(obj.size, 50.0), height=height,
            level=index, depth=-99.0, held=True))
    return (pad_x, pad_y, max(width, 128.0), 166.0 + 40.0 * (len(held) - 1))


def _place_labels(drawing: RenderPlan) -> None:
    """Give every shape a plate, looking for a spot that is actually free.

    A plate must clear two things: the other plates (or two labels become one
    unreadable blob) and the other objects' bodies (or a label appears to
    belong to the wrong block).  Preferred position is directly above the
    object; failing that it steps further up, then down.
    """
    taken: List[Tuple[float, float, float, float]] = []
    for shape in sorted(drawing.shapes, key=lambda s: (s.cx, s.base_y, s.ident)):
        others = [(s.x, s.top, s.width, s.bottom - s.top)
                  for s in drawing.shapes if s.ident != shape.ident]
        middle = (shape.top + shape.bottom) / 2.0

        candidates: List[Tuple[float, float, str]] = [
            (shape.cx - LABEL_W / 2.0, shape.top - LEADER - LABEL_H, "above")
        ]
        for step in range(14):
            # sides come before climbing higher: when something is stacked on
            # top, "above" is blocked, and stepping further up just piles one
            # plate on another instead of finding a clear spot
            side = step * (LABEL_W + 8)
            candidates.append((shape.x - LEADER - LABEL_W - side,
                               middle - LABEL_H / 2.0, "left"))
            candidates.append((shape.x + shape.width + LEADER + side,
                               middle - LABEL_H / 2.0, "right"))
            if step:
                gap = step * (LABEL_H + 5)
                candidates.append((shape.cx - LABEL_W / 2.0,
                                   shape.top - LEADER - LABEL_H - gap, "above"))
        candidates.append((shape.cx - LABEL_W / 2.0,
                           shape.bottom + LEADER, "below"))

        chosen = None
        for left, y, side_name in candidates:
            if _is_free(left, y, taken) and _is_free(left, y, others):
                chosen = (left, y, side_name)
                break
        if chosen is None:
            chosen = (shape.cx - LABEL_W / 2.0,
                      shape.top - LEADER - LABEL_H, "above")
        shape.label_x, shape.label_y, shape.label_side = chosen
        taken.append((shape.label_x, shape.label_y, LABEL_W, LABEL_H))


def _is_free(left: float, top: float,
             taken: Sequence[Tuple[float, float, float, float]]) -> bool:
    for other_left, other_top, other_w, other_h in taken:
        if (left < other_left + other_w and other_left < left + LABEL_W
                and top < other_top + other_h and other_top < top + LABEL_H):
            return False
    return True


def _fit_canvas(drawing: RenderPlan, labels: bool) -> None:
    shapes = drawing.shapes
    if not shapes:
        drawing.width = drawing.height = MARGIN * 2
        return

    xs = [s.x for s in shapes] + [p[0] for p in drawing.table]
    ys = [s.top for s in shapes] + [p[1] for p in drawing.table]
    xe = [s.x + s.width for s in shapes] + [p[0] for p in drawing.table]
    ye = [s.bottom for s in shapes] + [p[1] for p in drawing.table]
    if drawing.hand_pad:
        px, py, pw, ph = drawing.hand_pad
        xs.append(px); ys.append(py); xe.append(px + pw); ye.append(py + ph)
    if labels:
        xs += [s.label_x for s in shapes]
        ys += [s.label_y for s in shapes]
        xe += [s.label_x + LABEL_W for s in shapes]
        ye += [s.label_y + LABEL_H for s in shapes]

    dx, dy = MARGIN - min(xs), MARGIN - min(ys)
    for shape in shapes:
        shape.move(dx, dy)
    drawing.table = [(x + dx, y + dy) for x, y in drawing.table]
    if drawing.hand_pad:
        px, py, pw, ph = drawing.hand_pad
        drawing.hand_pad = (px + dx, py + dy, pw, ph)

    drawing.width = max(max(xe) - min(xs) + 2 * MARGIN, 360.0)
    drawing.height = max(max(ye) - min(ys) + 2 * MARGIN, 300.0)


# --------------------------------------------------------------------------
# Reading the drawing back
# --------------------------------------------------------------------------


def read_back(render: RenderPlan) -> Dict[str, object]:
    """Reconstruct a state from the drawn geometry.

    Stacking is **inferred** by comparing the drawn faces — an object rests on another when its underside
    sits exactly on that one's top face and their spans overlap.  Which table
    cell something occupies is not recovered: the picture does not claim to
    convey it, and no P0 question depends on it.
    """
    placed: List[Dict[str, object]] = []

    for shape in sorted(render.shapes, key=lambda s: (s.base_y, s.cx)):
        if shape.held:
            placed.append(_row(shape, ["hand"]))
            continue
        support = _resting_on(shape, render.shapes)
        placed.append(_row(shape, ["on", support.ident] if support else ["table"]))

    placed.sort(key=lambda row: str(row["id"]))
    return {"objects": placed, "hand": None}


def _row(shape: Shape, pos: List[object]) -> Dict[str, object]:
    return {"id": shape.ident, "kind": shape.kind, "color": shape.color,
            "size": shape.size, "pos": pos}


def _resting_on(shape: Shape, shapes: Sequence[Shape]) -> Optional[Shape]:
    """The object whose top face this one's underside sits on."""
    best: Optional[Shape] = None
    for other in shapes:
        if other.ident == shape.ident or other.held:
            continue
        if abs(shape.base_y - other.roof_y) > 0.5:
            continue
        overlap = (min(shape.cx + shape.half, other.cx + other.half)
                   - max(shape.cx - shape.half, other.cx - other.half))
        if overlap <= 0:
            continue
        if best is None or other.width > best.width:
            best = other
    return best


def relation_key(state: Dict[str, object]) -> Dict[str, tuple]:
    """A state reduced to what the picture is claimed to convey."""
    out: Dict[str, tuple] = {}
    for row in state.get("objects", []):  # type: ignore[union-attr]
        pos = list(row["pos"])
        kind = str(pos[0])
        rest = str(pos[1]) if kind in ("on", "in") and len(pos) > 1 else None
        out[str(row["id"])] = (row["color"], row["size"], row["kind"], kind, rest)
    return out


# --------------------------------------------------------------------------
# Faces
# --------------------------------------------------------------------------


def faces(shape: Shape) -> Dict[str, List[Tuple[float, float]]]:
    """The polygons to draw for this object, in painter's order."""
    cx, roof, base = shape.cx, shape.roof_y, shape.base_y
    half, dep, height = shape.half, shape.dep, shape.height

    if shape.kind == "ball":
        return {}
    if shape.kind == "pyramid":
        north = (cx, base - dep)
        east = (cx + half, base)
        south = (cx, base + dep)
        west = (cx - half, base)
        apex = (cx, base - height)
        return {"top": [west, south, north, east],
                "left": [west, south, apex],
                "right": [south, east, apex]}

    north = (cx, roof - dep)
    east = (cx + half, roof)
    south = (cx, roof + dep)
    west = (cx - half, roof)
    east_low = (cx + half, base)
    south_low = (cx, base + dep)
    west_low = (cx - half, base)
    out = {"top": [north, east, south, west],
           "left": [west, south, south_low, west_low],
           "right": [south, east, east_low, south_low]}
    return out


# --------------------------------------------------------------------------
# SVG
# --------------------------------------------------------------------------


def to_svg(world: World, labels: bool = True) -> str:
    return render_svg(plan(world, labels=labels), labels=labels)


def render_svg(render: RenderPlan, labels: bool = True) -> str:
    parts: List[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="%.0f" height="%.0f" viewBox="0 0 %.0f %.0f">'
        % (render.width, render.height, render.width, render.height),
        "<title>SHRDLU scene</title>",
    ]
    if render.table:
        parts.append('<polygon points="%s" fill="%s" stroke="%s" stroke-width="2"/>'
                     % (_points(render.table), TABLE_FILL, TABLE_EDGE))
    for area, caption, fill, edge in (
        (render.hand_pad, render.hand_caption, PAD_FILL, PAD_EDGE),
    ):
        if not area:
            continue
        ax, ay, aw, ah = area
        parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="12" '
                     'fill="%s" stroke="%s" stroke-width="2" stroke-dasharray="6 5"/>'
                     % (ax, ay, aw, ah, fill, edge))
        parts.append(_caption(ax + aw / 2.0, ay + ah - 12.0, caption, edge))

    for shape in render.draw_order():
        parts.append(_object(shape))

    if labels:
        for shape in render.shapes:
            parts.append(_label(shape))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _points(points: Sequence[Tuple[float, float]]) -> str:
    return " ".join("%.1f,%.1f" % (x, y) for x, y in points)


def _object(shape: Shape) -> str:
    base = colour_of(shape.color)
    edge = _shade(base, 0.55)
    if shape.kind == "ball":
        radius = shape.radius
        return ('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" stroke="%s" '
                'stroke-width="1.5"/>'
                % (shape.cx, shape.base_y - radius, radius, base, edge))

    polygons = faces(shape)
    shading = {"top": 1.28, "left": 1.0, "right": 0.72}
    parts = []
    for name in ("top", "left", "right"):
        if name not in polygons:
            continue
        parts.append('<polygon points="%s" fill="%s" stroke="%s" stroke-width="1.5"/>'
                     % (_points(polygons[name]), _shade(base, shading[name]), edge))
    return "".join(parts)


def silhouette(shape: Shape) -> List[Tuple[float, float]]:
    """The outline of what is actually drawn, as a convex polygon.

    A cuboid shows a hexagonal outline (top face plus the two side faces), but
    a pyramid tapers to a single apex, so its outline is a quadrilateral.  A
    ball has no polygon at all; :func:`touch_point` handles it separately.
    """
    cx, roof, base = shape.cx, shape.roof_y, shape.base_y
    half, dep, height = shape.half, shape.dep, shape.height
    if shape.kind == "pyramid":
        return [(cx, base - height), (cx + half, base),
                (cx, base + dep), (cx - half, base)]
    return [(cx, roof - dep), (cx + half, roof), (cx, base + dep),
            (cx - half, base), (cx - half, roof)]


def visual_centre(shape: Shape) -> Tuple[float, float]:
    """A point inside the drawn body, for aiming a leader at."""
    return shape.cx, (shape.top + shape.bottom) / 2.0


def drawn_body(shape: Shape, steps: int = 32) -> List[List[Tuple[float, float]]]:
    """The polygons actually painted for this object.

    Every kind comes back as polygons — a ball as a fine approximation of its
    circle — so anything that needs to test a point against the picture can do
    so without knowing how each kind is drawn.
    """
    if shape.kind == "ball":
        radius = shape.radius
        cx, cy = shape.cx, shape.base_y - radius
        ring = []
        for step in range(steps):
            angle = 2.0 * math.pi * step / steps
            ring.append((cx + radius * math.cos(angle),
                         cy + radius * math.sin(angle)))
        return [ring]
    return list(faces(shape).values())


def touch_point(shape: Shape, toward: Tuple[float, float]) -> Tuple[float, float]:
    """Where the object's outline meets a line coming from ``toward``.

    The end of a leader has to land *on* the object.  Aiming at a fixed corner
    of a bounding box only works for cuboids: a pyramid is narrow at the top,
    so a label beside it used to end in empty space.
    """
    centre = visual_centre(shape)
    vx, vy = toward[0] - centre[0], toward[1] - centre[1]
    if shape.kind == "ball":
        radius = shape.radius
        circle = (shape.cx, shape.base_y - radius)
        length = (vx * vx + vy * vy) ** 0.5 or 1.0
        return (circle[0] + radius * vx / length, circle[1] + radius * vy / length)
    hit = _ray_exit(centre, toward, silhouette(shape))
    return hit if hit is not None else toward


def _ray_exit(centre: Tuple[float, float], toward: Tuple[float, float],
              polygon: Sequence[Tuple[float, float]]
              ) -> Optional[Tuple[float, float]]:
    """First point where the ray ``centre -> toward`` leaves ``polygon``."""
    dx, dy = toward[0] - centre[0], toward[1] - centre[1]
    best: Optional[Tuple[float, float]] = None
    best_d = 0.0
    for i, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(i + 1) % len(polygon)]
        ex, ey = x2 - x1, y2 - y1
        denom = dx * ey - dy * ex
        if abs(denom) < 1e-9:
            continue
        ax, ay = x1 - centre[0], y1 - centre[1]
        t = (ax * ey - ay * ex) / denom
        u = (ax * dy - ay * dx) / denom
        if t > 1e-9 and -1e-9 <= u <= 1.0 + 1e-9:
            point = (centre[0] + t * dx, centre[1] + t * dy)
            if best is None or t < best_d:
                best, best_d = point, t
    return best


def leader(shape: Shape) -> Tuple[float, float, float, float]:
    """Where the line joining a label to its object starts and ends.

    The far end is the point where that line meets the object's own outline,
    whichever side the label ended up on.
    """
    left, top = shape.label_x, shape.label_y
    if shape.label_side == "above":
        start = (shape.cx, top + LABEL_H)
    elif shape.label_side == "below":
        start = (shape.cx, top)
    elif shape.label_side == "left":
        start = (left + LABEL_W, top + LABEL_H / 2.0)
    else:
        start = (left, top + LABEL_H / 2.0)
    end = touch_point(shape, start)
    return start[0], start[1], end[0], end[1]


def _caption(cx: float, baseline: float, text: str, colour: str) -> str:
    """Small grey text naming a region, so the picture explains itself."""
    if not text:
        return ""
    return ('<text x="%.1f" y="%.1f" font-family="sans-serif" font-size="13" '
            'fill="%s" text-anchor="middle">%s</text>'
            % (cx, baseline, colour, _xml(text)))


def _label(shape: Shape) -> str:
    left, top = shape.label_x, shape.label_y
    x1, y1, x2, y2 = leader(shape)
    return (
        '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.5"/>'
        '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="5" fill="%s" '
        'stroke="%s" stroke-width="1.5"/>'
        '<text x="%.1f" y="%.1f" font-family="monospace" font-size="15" '
        'font-weight="bold" fill="%s" text-anchor="middle">%s</text>'
        % (x1, y1, x2, y2, LABEL_EDGE,
           left, top, LABEL_W, LABEL_H, LABEL_FILL, LABEL_EDGE,
           left + LABEL_W / 2.0, top + LABEL_H - 6, LABEL_TEXT, _xml(shape.ident))
    )


def _ensure_parent(path: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)


def save(world: World, path: str, labels: bool = True) -> str:
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(to_svg(world, labels=labels))
    return path


# --------------------------------------------------------------------------
# PNG (optional, needs Pillow)
# --------------------------------------------------------------------------


def to_png(world: World, path: str, labels: bool = True, scale: float = 2.0) -> str:
    """Draw the same plan with Pillow.  Most vision models want PNG, not SVG."""
    to_png_bytes(world, labels=labels, scale=scale, destination=path)
    return path


def to_png_bytes(world: World, labels: bool = True, scale: float = 2.0,
                 destination: Optional[str] = None) -> bytes:
    """The picture as bytes, for sending to a model over the wire.

    Nothing about the drawing depends on the destination: the same image is
    written to a file and shipped in a message.
    """
    Image, ImageDraw, ImageFont = _pillow()
    drawing = plan(world, labels=labels)
    image = Image.new("RGB", (int(drawing.width * scale), int(drawing.height * scale)),
                      "white")
    pen = ImageDraw.Draw(image)

    def pt(point):
        return (point[0] * scale, point[1] * scale)

    def rgb(name):
        name = name.lstrip("#")
        return tuple(int(name[i:i + 2], 16) for i in (0, 2, 4))

    def tint(name, factor):
        return tuple(max(0, min(255, int(round(v * factor)))) for v in rgb(name))

    if drawing.table:
        pen.polygon([pt(p) for p in drawing.table], fill=rgb(TABLE_FILL),
                    outline=rgb(TABLE_EDGE))
    caption_font = _font(ImageFont, max(int(12 * scale), 10))
    for area, caption in ((drawing.hand_pad, drawing.hand_caption),):
        if not area:
            continue
        ax, ay, aw, ah = area
        pen.rounded_rectangle([pt((ax, ay)), pt((ax + aw, ay + ah))],
                              radius=12 * scale, fill=rgb(PAD_FILL),
                              outline=rgb(PAD_EDGE), width=2)
        if caption:
            pen.text(pt((ax + aw / 2.0, ay + ah - 14.0)), caption,
                     fill=rgb(PAD_EDGE), font=caption_font, anchor="mm")

    for shape in drawing.draw_order():
        base = colour_of(shape.color)
        edge = _shade(base, 0.55)
        if shape.kind == "ball":
            radius = shape.radius
            pen.ellipse([pt((shape.cx - radius, shape.base_y - 2 * radius)),
                         pt((shape.cx + radius, shape.base_y))],
                        fill=rgb(base), outline=rgb(edge), width=2)
            continue
        polygons = faces(shape)
        for name, factor in (("top", 1.28), ("left", 1.0), ("right", 0.72)):
            if name in polygons:
                pen.polygon([pt(p) for p in polygons[name]], fill=tint(base, factor),
                            outline=rgb(edge))

    if labels:
        font = _font(ImageFont, int(15 * scale))
        for shape in drawing.shapes:
            left, top = shape.label_x, shape.label_y
            x1, y1, x2, y2 = leader(shape)
            pen.line([pt((x1, y1)), pt((x2, y2))],
                     fill=rgb(LABEL_EDGE), width=max(1, int(scale)))
            pen.rounded_rectangle([pt((left, top)), pt((left + LABEL_W, top + LABEL_H))],
                                  radius=5 * scale, fill="white",
                                  outline=rgb(LABEL_EDGE), width=2)
            pen.text(pt((left + LABEL_W / 2.0, top + LABEL_H / 2.0)), shape.ident,
                     fill=rgb(LABEL_TEXT), font=font, anchor="mm")

    if destination is not None:
        _ensure_parent(destination)
        image.save(destination)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RenderError(
            "PNG output needs Pillow (pip install pillow); SVG output does not"
        ) from exc
    return Image, ImageDraw, ImageFont


def _font(ImageFont, size: int):
    for candidate in (
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


# --------------------------------------------------------------------------
# Auditing the drawing
# --------------------------------------------------------------------------


def audit(drawing: RenderPlan, labels: bool = True) -> List[str]:
    """Faults that make the picture wrong or unreadable.  Fatal if non-empty."""
    problems: List[str] = []
    if not drawing.shapes:
        return ["nothing was drawn"]

    for shape in drawing.shapes:
        if (shape.x < 0 or shape.top < 0
                or shape.x + shape.width > drawing.width
                or shape.bottom > drawing.height):
            problems.append("%s falls outside the canvas" % shape.ident)

    seen: Dict[Tuple[float, float, float], str] = {}
    for shape in drawing.shapes:
        slot = (round(shape.cx, 1), round(shape.base_y, 1), round(shape.width, 1))
        if slot in seen:
            problems.append("%s and %s are drawn in exactly the same place"
                            % (seen[slot], shape.ident))
        seen[slot] = shape.ident

    if labels:
        problems.extend(_label_problems(drawing))
    return problems


def _label_problems(drawing: RenderPlan) -> List[str]:
    problems: List[str] = []
    plates: List[Tuple[str, float, float]] = []
    for shape in drawing.shapes:
        left, top = shape.label_x, shape.label_y
        plates.append((shape.ident, left, top))
        if left < 0 or top < 0:
            problems.append("the label for %s falls off the canvas" % shape.ident)
        if left + LABEL_W > drawing.width or top + LABEL_H > drawing.height:
            problems.append("the label for %s runs off the edge" % shape.ident)

    for index, (ident_a, ax, ay) in enumerate(plates):
        for ident_b, bx, by in plates[index + 1:]:
            if (ax < bx + LABEL_W and bx < ax + LABEL_W
                    and ay < by + LABEL_H and by < ay + LABEL_H):
                problems.append("the labels for %s and %s overlap" % (ident_a, ident_b))
    return problems


def size_warnings(drawing: RenderPlan) -> List[str]:
    """Legibility problems that do not mean the picture is wrong."""
    warnings: List[str] = []
    for shape in drawing.shapes:
        if shape.width < MIN_SHAPE or shape.height < MIN_SHAPE:
            warnings.append("%s is drawn small (%.0fx%.0f)"
                            % (shape.ident, shape.width, shape.height))
    if len({s.size for s in drawing.shapes}) > 1:
        big = max((s.width for s in drawing.shapes if s.size == "big"), default=0.0)
        small = min((s.width for s in drawing.shapes if s.size == "small"), default=0.0)
        if small and big / small < 1.25:
            warnings.append("big and small objects are nearly the same width")
    return warnings
