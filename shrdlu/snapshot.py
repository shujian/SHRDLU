"""Canonical JSON representation of a world state (protocol §1).

This is the single serialisation format shared by the env program and the
testee program:

    {
      "objects": [
        {"id": "b", "kind": "cube", "color": "red", "size": "big",
         "pos": ["table"]},
        {"id": "a", "kind": "cube", "color": "green", "size": "small",
         "pos": ["on", "b"]}
      ],
      "hand": null
    }

This is the **only** snapshot format.  There used to be a second, private one
inside ``world.py`` for cloning; nothing used it, and two formats for one thing
is one too many.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from .world import Obj, World, WorldError, check_consistent

TABLE = "table"


class SnapshotError(Exception):
    """Raised when a snapshot cannot be turned back into a world."""


def object_row(world: World, obj: Obj) -> Dict[str, object]:
    """One object in canonical form."""
    return {
        "id": obj.ident,
        "kind": obj.kind,
        "color": obj.color,
        "size": obj.size,
        "pos": list(world.pos_of(obj)),
    }


def to_snapshot(world: World) -> Dict[str, object]:
    """The whole world in canonical form."""
    return {
        "objects": [object_row(world, o) for o in world.actual_objects()],
        "hand": world.hand,
    }


def _pos_of_row(row: Dict[str, object]) -> List[object]:
    """A row's position: ``["table"]``, ``["on", id]`` or ``["hand"]``.

    Nothing but relations, because that is all a position is.  There is no cell
    to omit, invent, or get out of step with what rests on what.
    """
    pos = row.get("pos")
    if not pos:
        return [TABLE]
    if isinstance(pos, (list, tuple)):
        return list(pos)
    raise SnapshotError("bad pos for %r: %r" % (row.get("id"), pos))


def from_snapshot(data: Dict[str, object]) -> World:
    """Rebuild a world from canonical form."""
    world = World()
    rows: List[Dict[str, object]] = [dict(r) for r in (data.get("objects") or [])]
    if not rows:
        raise SnapshotError("snapshot has no objects")

    seen = set()
    for row in rows:
        ident = str(row["id"])
        if ident in seen:
            raise SnapshotError("duplicate object id: %s" % ident)
        seen.add(ident)

    # Create every object first, so that any id can be referred to, then say
    # what rests on what.  The order rows appear in never matters, and a chain
    # of any depth resolves in one pass.
    for row in rows:
        world.add(
            kind=str(row.get("kind", "cube")),
            color=str(row.get("color", "")),
            size=str(row.get("size", "small")),
            on=TABLE,
            ident=str(row["id"]),
        )

    held: List[str] = []
    for row in rows:
        ident = str(row["id"])
        pos = _pos_of_row(row)
        form = pos[0]
        if form == TABLE:
            continue
        if form not in ("on", "hand"):
            raise SnapshotError("unknown position form %r for %s" % (form, ident))
        if form == "hand":
            held.append(ident)
            continue
        base = str(pos[1])
        if base not in world.objects:
            raise SnapshotError("%s is %s unknown object %s" % (ident, form, base))
        try:
            world.set_pos(ident, (form, base))
        except WorldError as exc:
            raise SnapshotError("%s: %s" % (ident, exc)) from exc

    try:
        for ident in held:
            world.set_pos(ident, ("hand",))
        hand = data.get("hand")
        if hand:
            world.set_pos(str(hand), ("hand",))
    except WorldError as exc:
        raise SnapshotError("bad 'hand': %s" % exc) from exc

    # Refuse to hand back a world that cannot exist.  Every field above is
    # checked for *existence* as it is applied, but nothing checks that the
    # result makes sense together — and a cycle of supports is expressible and
    # would otherwise sit in the world looking like a position.  Wrong input
    # should fail here, loudly, rather than somewhere far away and strange.
    problems = check_consistent(world)
    if problems:
        raise SnapshotError("inconsistent state: %s" % "; ".join(problems))
    return world


def dumps(world: World) -> str:
    return json.dumps(to_snapshot(world), ensure_ascii=False, indent=2)


def loads(text: str) -> World:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise SnapshotError("not valid JSON: %s" % exc)
    if not isinstance(data, dict):
        raise SnapshotError("snapshot must be a JSON object")
    return from_snapshot(data)


def clone(world: World) -> World:
    """A deep, independent copy of ``world``."""
    return from_snapshot(to_snapshot(world))


def describe(world: World, obj: object) -> str:
    """Human phrase for an object plus where it is, e.g. ``big red cube on table``."""
    target = world.resolve(obj)
    pos = world.pos_of(target)
    if pos[0] == "table":
        where = "on the table"
    elif pos[0] == "hand":
        where = "in hand"
    elif pos[0] == "in":
        where = "in %s" % pos[1]
    else:
        where = "on %s" % pos[1]
    return "%s %s (%s)" % (target.describe(), target.ident, where)


def place_text(world: World, obj: object) -> str:
    """A short phrase for where something is: "on the table", "on b", "in hand"."""
    pos = world.pos_of(obj)
    if pos[0] == "table":
        return "on the table"
    if pos[0] == "hand":
        return "in hand"
    if pos[0] == "in":
        return "in %s" % pos[1]
    return "on %s" % pos[1]


def differences(truth: World, other: Optional[World]) -> List[Tuple[str, str, str]]:
    """``(id, what is true, what the other state says)`` for every disagreement.

    The env uses this to compare its two states after every operation
    (:mod:`shrdlu.host`), and the viewers use it to *show* that comparison, so
    the two can never disagree about what "the states differ" means.
    """
    if other is None:
        return []
    out: List[Tuple[str, str, str]] = []
    for obj in truth.actual_objects():
        ident = obj.ident
        mine = place_text(truth, ident)
        theirs = place_text(other, ident) if other.get(ident) else "(不存在)"
        if mine != theirs:
            out.append((ident, mine, theirs))
    return out
