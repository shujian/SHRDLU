"""Blocks world: the fact base that a SHRDLU judger reasons about.

The model follows Winograd's SHRDLU closely enough to be recognisable while
staying simple enough to be inspectable:

  * Where an object is, is given entirely by **what it rests on**.  An object
    that rests on nothing is on the table; two objects are in the same column
    exactly when one rests on the other.  There are no coordinates: a position
    cannot disagree with the relations, because it *is* a relation.
  * A single robot hand can hold at most one object.

Nothing here knows about English.  ``world.py`` is pure state plus the
predicates that the semantic layer in :mod:`shrdlu.semantics` evaluates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

#: Objects that can never be picked up.  ``world`` is the whole scene and
#: ``table`` is the surface everything ultimately rests on.
FIXED_OBJECTS = ("table", "world")

KIND_NAMES = ("block", "cube", "pyramid", "ball", "thing", "object")

COLOR_NAMES = (
    "red",
    "green",
    "blue",
    "yellow",
    "white",
    "black",
    "brown",
    "orange",
    "purple",
    "grey",
    "gray",
    "pink",
    "cyan",
    "magenta",
)

SIZE_NAMES = ("big", "large", "small", "little", "medium", "tiny")

SUPPORTING_KINDS = ("cube",)


class WorldError(Exception):
    """Raised when an operation would violate the physics of the world."""


# --------------------------------------------------------------------------
# Objects
# --------------------------------------------------------------------------


@dataclass
class Obj:
    """A single manipulable object, or one of the fixed pseudo-objects."""

    ident: str
    kind: str
    color: str
    size: str
    #: The id of whatever holds this object up; ``None`` means the table.
    support: Optional[str] = None
    held: bool = False
    props: Dict[str, object] = field(default_factory=dict)

    # -- derived -----------------------------------------------------------
    @property
    def is_fixed(self) -> bool:
        return self.ident in FIXED_OBJECTS

    @property
    def supports_things(self) -> bool:
        return self.kind in SUPPORTING_KINDS

    def describe(self) -> str:
        """A human phrase such as ``big red cube``, without an article."""
        parts: List[str] = []
        if self.size in ("big", "large"):
            parts.append("big")
        elif self.size in ("small", "little", "tiny"):
            parts.append("small")
        if self.color:
            parts.append(self.color)
        if self.kind in ("block", "cube", "pyramid", "ball"):
            parts.append("cube" if self.kind == "block" else self.kind)
        elif not parts:
            parts.append(self.kind)
        return " ".join(parts)

    def to_json(self) -> Dict[str, object]:
        out: Dict[str, object] = {
            "name": self.ident,
            "kind": self.kind,
            "color": self.color,
            "size": self.size,
            "held": self.held,
        }
        if self.support:
            out["on"] = self.support
        return out


# --------------------------------------------------------------------------
# World
# --------------------------------------------------------------------------


class World:
    """Mutable blocks world with a single robot hand."""

    def __init__(self) -> None:
        self.objects: Dict[str, Obj] = {}
        self.hand: Optional[str] = None
        self._counter = count(1)
        self._add_fixed_objects()

    # -- construction ------------------------------------------------------
    def _add_fixed_objects(self) -> None:
        self.objects["table"] = Obj("table", "table", "", "")
        self.objects["world"] = Obj("world", "world", "", "")

    def fresh_ident(self, kind: str) -> str:
        while True:
            ident = "%s-%d" % (kind, next(self._counter))
            if ident not in self.objects:
                return ident

    def add(
        self,
        kind: str,
        color: str = "",
        size: str = "small",
        on: object = "table",
        ident: Optional[str] = None,
    ) -> Obj:
        """Add an object resting on ``on``: an id, an :class:`Obj`, or the table.

        Which *column* it stands in is not a separate thing to specify.  Where an
        object is, is given entirely by what it rests on: an object that rests on
        nothing is on the table, and two objects are in the same column exactly
        when one rests on the other.  There is no coordinate to get out of step
        with that.
        """
        if ident is None:
            ident = self.fresh_ident(kind)
        if ident in self.objects:
            raise WorldError("duplicate object id: %s" % ident)
        if isinstance(on, Obj):
            on = on.ident
        if on == "table":
            base = None
        elif on in self.objects:
            base = self.objects[on]
        else:
            raise WorldError("unknown support: %r" % (on,))
        obj = Obj(ident, kind, color, size)
        if base is not None:
            self._attach(obj, base)
        self.objects[ident] = obj
        return obj

    def remove(self, obj: object) -> None:
        """Delete an object from the world.  **Not a protocol operation.**

        This is the state-edit API the tests use to build a deliberately broken
        model — "a testee that never noticed this object exists is missing" —
        so the divergence views have something to show.  No operation in O0
        removes anything.

        Anything that rested on it is left standing on the table rather than
        being deleted with it.  That is a decision, not an accident: a test
        that removes one object from a model wants the rest of the scene to
        stay comparable.  Nothing validates the result; call
        :func:`check_consistent` if it matters.
        """
        target = self.resolve(obj)
        if target.is_fixed:
            raise WorldError("cannot remove %s" % target.ident)
        if self.hand == target.ident:
            self.hand = None
        for other in self.objects.values():
            if other.support == target.ident:
                other.support = None
        del self.objects[target.ident]

    # -- lookup ------------------------------------------------------------
    def resolve(self, obj: object) -> Obj:
        """Accept an id, an :class:`Obj`, or ``None`` and return a real object."""
        if isinstance(obj, Obj):
            return obj
        if obj is None:
            raise WorldError("no such object: None")
        if isinstance(obj, str):
            if obj in self.objects:
                return self.objects[obj]
            raise WorldError("no such object: %s" % obj)
        raise WorldError("cannot resolve %r" % (obj,))

    def get(self, ident: str) -> Optional[Obj]:
        return self.objects.get(ident)

    def all_objects(self, include_fixed: bool = False) -> List[Obj]:
        """Every object, in a stable order (creation order)."""
        items = [o for o in self.objects.values() if include_fixed or not o.is_fixed]
        return items

    def actual_objects(self) -> List[Obj]:
        return self.all_objects(include_fixed=False)

    # -- protocol view -----------------------------------------------------
    def pos_of(self, obj: object) -> Tuple[object, ...]:
        """The object's position in the protocol's canonical form.

        ``("table",)`` | ``("on", support_id)`` | ``("hand",)``
        """
        target = self.resolve(obj)
        if target.held:
            return ("hand",)
        if target.support is not None:
            return ("on", target.support)
        return ("table",)

    def is_supported(self, obj: object) -> bool:
        """True when the object rests on something other than the table."""
        return self.pos_of(obj)[0] == "on"

    def set_pos(self, obj: object, pos: Sequence[object]) -> Obj:
        """Move ``obj`` to a position given in the protocol's canonical form.

        This is the inverse of :meth:`pos_of`, used when loading a scenario or
        a snapshot.  It performs no legality checking: it is a state edit, not
        an operation.
        """
        target = self.resolve(obj)
        if not isinstance(pos, (list, tuple)) or not pos:
            raise WorldError("position must be a non-empty sequence")
        form = pos[0]
        if form not in ("hand", "table", "on"):
            raise WorldError("unknown position form: %r" % (form,))
        expected = 1 if form in ("hand", "table") else 2
        if len(pos) != expected:
            raise WorldError("position %r expects %d item(s)" % (form, expected))
        base = None
        if form == "on":
            base = self.resolve(pos[1])
            if base.ident == target.ident:
                raise WorldError("an object cannot be placed on itself")
        target.held = form == "hand"
        if target.held:
            target.support = None
            self.hand = target.ident
        else:
            if self.hand == target.ident:
                self.hand = None
            target.support = base.ident if base is not None else None
        return target

    def _attach(self, obj: Obj, base: Obj) -> None:
        """Rest ``obj`` on ``base``."""
        obj.support = base.ident

    # -- predicates --------------------------------------------------------
    def is_on(self, a: object, b: object) -> bool:
        """True when ``a`` rests on ``b``, directly or through other objects."""
        x = self.resolve(a)
        y = self.resolve(b)
        if x.ident == y.ident:
            return False
        if y.kind == "world":
            return True
        if x.held:
            return False
        walker: Optional[Obj] = x
        while walker is not None:
            support = self.support_of(walker)
            if support is None:
                return False
            if support.ident == y.ident:
                return True
            walker = None if support.is_fixed else support
        return False

    def directly_on(self, a: object, b: object) -> bool:
        """True when ``a`` is immediately supported by ``b``.

        One comparison, because the support pointer *is* the relation: an
        object rests on exactly one thing, and that is what it says it rests on.
        """
        x = self.resolve(a)
        y = self.resolve(b)
        if x.ident == y.ident:
            return False
        if y.kind == "world":
            return False
        if x.held:
            return False
        if y.kind == "table":
            return x.support is None
        return x.support == y.ident

    def support_of(self, obj: object) -> Optional[Obj]:
        """The object immediately underneath ``obj``, or ``None``.

        An object on the table answers with the table itself, so a caller never
        has to distinguish "nothing below it" from "the table below it".
        """
        x = self.resolve(obj)
        if x.is_fixed or x.held:
            return None
        if x.support is None:
            return self.objects["table"]
        return self.get(x.support)

    def is_clear(self, obj: object) -> bool:
        x = self.resolve(obj)
        if x.is_fixed or x.held:
            return False
        if x.kind == "pyramid":
            return True  # nothing balances on a pointed top
        return self.height(x) == 0

    def height(self, obj: object, _seen: Optional[set] = None) -> int:
        """How many objects sit on top of ``obj`` (transitively)."""
        target = self.resolve(obj)
        seen = set() if _seen is None else _seen
        if target.ident in seen:          # a cycle; check_consistent reports it
            return 0
        seen.add(target.ident)
        above = [o for o in self.actual_objects()
                 if o.support == target.ident and not o.held]
        if not above:
            return 0
        return 1 + max(self.height(o, seen) for o in above)

    def chain(self, root: object) -> List[Obj]:
        """``root`` and everything standing on it, bottom first."""
        out = [self.resolve(root)]
        while True:
            above = [o for o in self.actual_objects()
                     if o.support == out[-1].ident and o not in out]
            if not above:
                return out
            out.append(above[0])

    # -- actions -----------------------------------------------------------
    def pick_up(self, obj: object) -> Obj:
        target = self.resolve(obj)
        if target.is_fixed:
            raise WorldError("I cannot pick up the %s." % target.kind)
        if self.hand is not None:
            raise WorldError("My hand is already full.")
        if not self.is_clear(target):
            raise WorldError("The %s is not clear." % target.describe())
        target.held = True
        self.hand = target.ident
        return target

    def put_down(self, obj: object) -> Obj:
        """Take ``obj`` out of the hand and stand it on the table."""
        target = self.resolve(obj)
        if self.hand != target.ident:
            raise WorldError("I am not holding the %s." % target.describe())
        target.held = False
        self.hand = None
        target.support = None
        return target

def initial_world() -> World:
    """The scene from Winograd's thesis: four objects on a bare table.

    A small green cube, a large red cube, a large blue cube, a large blue
    pyramid and a large yellow cube.
    """
    w = World()
    w.add("cube", "green", "small", ident="a")
    w.add("cube", "red", "big", ident="b")
    w.add("cube", "blue", "big", ident="c")
    w.add("pyramid", "blue", "big", ident="d")
    w.add("cube", "yellow", "big", ident="e")
    return w


def check_consistent(world: World) -> List[str]:
    """Return physics complaints about ``world``; empty means consistent.

    The complaints are all about the *pointers*, because that is all a position
    is made of now: it rests on one object, or it is in the hand.  What used to
    be impossible by construction — three objects
    in one column at the same height, or an object floating halfway up — cannot
    even be written down any more.  What *can* be written down is a loop, so
    that is checked explicitly.
    """
    problems: List[str] = []
    for obj in world.actual_objects():
        if obj.support == obj.ident:
            problems.append("%s rests on itself" % obj.ident)
        if obj.held and obj.support:
            problems.append("%s is in the hand and also placed" % obj.ident)
        if obj.support:
            support = world.get(obj.support)
            if support is None:
                problems.append("%s rests on unknown object %s" % (obj.ident, obj.support))
            elif not support.supports_things:
                problems.append("%s rests on the %s, which cannot support"
                                % (obj.ident, support.kind))
            elif support.held:
                problems.append("%s rests on %s, which is in the hand"
                                % (obj.ident, support.ident))
        # a loop of supports would make "what holds this up" meaningless
        seen = {obj.ident}
        walker = world.get(obj.support) if obj.support else None
        while walker is not None:
            if walker.ident in seen:
                problems.append("%s is in a cycle of supports" % obj.ident)
                break
            seen.add(walker.ident)
            walker = world.get(walker.support) if walker.support else None

    if world.hand is not None:
        held = world.get(world.hand)
        if held is None:
            problems.append("the hand holds unknown object %s" % world.hand)
        elif not held.held:
            problems.append("%s is in the hand but not marked held" % world.hand)
    for obj in world.actual_objects():
        if obj.held and world.hand != obj.ident:
            problems.append("%s is marked held but is not in the hand" % obj.ident)
    return problems


def make_world(rows: Iterable[Dict[str, object]]) -> World:
    """Build a world from ``{"name", "kind", "color", "size", "on"}`` dicts."""
    w = World()
    for row in rows:
        w.add(
            str(row.get("kind", "block")),
            str(row.get("color", "")),
            str(row.get("size", "small")),
            on=str(row.get("on", "table")),
            ident=str(row["name"]) if row.get("name") else None,
        )
    return w
