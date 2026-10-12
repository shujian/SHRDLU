"""English rendering of O0 instructions.

The env sends an instruction as an English sentence (protocol D1) that refers
to objects by description, not by id.  Resolving that description back to an
object is part of what the testee is being tested on, so the env must phrase
each reference so that it is *unambiguous in the true state* — otherwise the
instruction would be unfair.
"""

from __future__ import annotations

from typing import List, Sequence

from ..world import Obj, World, WorldError

#: Kinds we know how to describe in words.
_DESCRIBABLE = ("cube", "pyramid", "ball")

#: Adjectives accepted as synonyms when deciding whether a phrase is unique.
_SYNONYMS = {
    "large": "big",
    "huge": "big",
    "little": "small",
    "tiny": "small",
    "block": "cube",
}


def referring_phrase(world: World, obj: object) -> str:
    """A description picking out exactly ``obj`` in ``world``, without article.

    Shortest unique wording wins: colour + kind, then size + colour + kind,
    then kind alone, then the object's id as a last resort.
    """
    target = world.resolve(obj)
    others = [o for o in world.actual_objects() if o.ident != target.ident]

    candidates: List[str] = []
    if target.color and target.kind in _DESCRIBABLE:
        candidates.append("%s %s" % (target.color, target.kind))
    if target.size and target.color and target.kind in _DESCRIBABLE:
        candidates.append("%s %s %s" % (target.size, target.color, target.kind))
    if target.kind in _DESCRIBABLE:
        candidates.append(target.kind)

    for phrase in candidates:
        if _is_unique(phrase, others):
            return phrase
    return target.ident


def _is_unique(phrase: str, others: Sequence[Obj]) -> bool:
    words = [_SYNONYMS.get(w, w) for w in phrase.split()]
    return not any(_described_by(o, words) for o in others)


def _described_by(obj: Obj, words: Sequence[str]) -> bool:
    """Would every word of ``phrase`` be true of ``obj``?"""
    for word in words:
        if word == obj.kind:
            continue
        if word == obj.color:
            continue
        if word == obj.size:
            continue
        return False
    return True


def render_instruction(world: World, op: str, args: Sequence[object]) -> str:
    """The English sentence the env sends for one instruction."""
    if op == "pick_up":
        return "Pick up the %s." % referring_phrase(world, args[0])
    if op == "put_down":
        return "Put down the %s." % referring_phrase(world, args[0])
    if op == "put_on":
        return "Put the %s on the %s." % (
            referring_phrase(world, args[0]),
            referring_phrase(world, args[1]),
        )
    raise WorldError("unknown operation %r" % op)
