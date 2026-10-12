"""The O0 operation set: legality checks and application (protocol §3).

Kept separate from :mod:`shrdlu.world` on purpose:

* ``world.py`` is the raw physics (positions, stacking, the hand);
* ``ops.py`` is the *protocol layer* — the four rules a testee is judged by.

Every operation has a ``check_*`` that returns ``None`` when legal or a short
reason when not, so a testee can decide whether to act or to refuse **without
executing anything**.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional, Sequence, Tuple

from .world import Obj, World, WorldError


class IllegalAction(WorldError):
    """Raised when an operation is not permitted in the current state."""


#: Operation name -> number of arguments.
OP_ARITY: Dict[str, int] = {
    "pick_up": 1,
    "put_down": 1,
    "put_on": 2,
}

OPERATIONS: Tuple[str, ...] = ("pick_up", "put_down", "put_on")


@dataclass
class Verdict:
    """The outcome of checking one operation."""

    op: str
    args: Tuple[str, ...]
    legal: bool
    reason: Optional[str] = None

    def __bool__(self) -> bool:
        return self.legal


def _resolve(world: World, ident: object) -> Optional[Obj]:
    try:
        return world.resolve(ident)
    except WorldError:
        return None


def _blocked_by_hand(world: World, x: Obj) -> Optional[str]:
    """Common gate for operations that need x in hand (possibly implicitly)."""
    if world.hand is None:
        return None  # will pick up implicitly
    if world.hand != x.ident:
        return "the hand is not empty"
    return None


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def check_pick_up(world: World, x: object) -> Optional[str]:
    target = _resolve(world, x)
    if target is None:
        return "there is no object called %r" % (x,)
    if target.is_fixed:
        return "the %s cannot be picked up" % target.kind
    if world.hand is not None:
        return "the hand is not empty"
    if not world.is_clear(target):
        return "the %s is not clear" % target.describe()
    return None


def check_put_down(world: World, x: object) -> Optional[str]:
    target = _resolve(world, x)
    if target is None:
        return "there is no object called %r" % (x,)
    if world.hand != target.ident:
        return "the %s is not in my hand" % target.describe()
    return None


def check_put_on(world: World, x: object, y: object) -> Optional[str]:
    source = _resolve(world, x)
    if source is None:
        return "there is no object called %r" % (x,)
    goal = _resolve(world, y)
    if goal is None:
        return "there is no object called %r" % (y,)
    if source.ident == goal.ident:
        return "an object cannot be put on itself"
    if goal.is_fixed:
        return "the %s cannot have things put on it" % goal.kind
    if not goal.supports_things:
        return "the %s cannot support anything" % goal.describe()

    if world.hand != source.ident:
        reason = _blocked_by_hand(world, source)
        if reason:
            return reason
        if world.hand is None:
            reason = check_pick_up(world, source.ident)
            if reason:
                return reason

    if not world.is_clear(goal) and not world.directly_on(source, goal):
        return "the %s is not clear" % goal.describe()
    return None


CHECKS: Dict[str, Callable[..., Optional[str]]] = {
    "pick_up": check_pick_up,
    "put_down": check_put_down,
    "put_on": check_put_on,
}


def legal_operations(world: World) -> List[Tuple[str, Tuple[str, ...]]]:
    """Every operation that would be legal in the current state.

    Used to decide whether a scene gives an instruction generator anything to
    work with, and to pick instructions without guessing.
    """
    ids = [o.ident for o in world.actual_objects()]
    legal: List[Tuple[str, Tuple[str, ...]]] = []
    for x in ids:
        if check_pick_up(world, x) is None:
            legal.append(("pick_up", (x,)))
        if check_put_down(world, x) is None:
            legal.append(("put_down", (x,)))
    for a in ids:
        for b in ids:
            if a == b:
                continue
            if check_put_on(world, a, b) is None:
                legal.append(("put_on", (a, b)))
    return legal


def check(world: World, op: str, args: Sequence[object]) -> Verdict:
    """Check one operation without changing the world."""
    if op not in OP_ARITY:
        return Verdict(op, tuple(str(a) for a in args), False, "unknown operation %r" % op)
    if len(args) != OP_ARITY[op]:
        return Verdict(
            op,
            tuple(str(a) for a in args),
            False,
            "%s takes %d argument(s), got %d" % (op, OP_ARITY[op], len(args)),
        )
    reason = CHECKS[op](world, *args)
    return Verdict(op, tuple(str(a) for a in args), reason is None, reason)


# --------------------------------------------------------------------------
# Application
# --------------------------------------------------------------------------


def _ensure_in_hand(world: World, source: Obj) -> None:
    """Pick ``source`` up if it is not already held (implicit pickup, §3.1)."""
    if world.hand != source.ident:
        world.pick_up(source)


def apply(world: World, op: str, args: Sequence[object]) -> str:
    """Apply an operation, or raise :class:`IllegalAction`.

    Returns a short human-readable description of what happened.
    """
    verdict = check(world, op, args)
    if not verdict.legal:
        raise IllegalAction(verdict.reason or "illegal operation")

    x = world.resolve(args[0])
    if op == "pick_up":
        world.pick_up(x)
        return "picked up %s" % x.describe()

    if op == "put_down":
        world.put_down(x)
        return "put down %s" % x.describe()

    y = world.resolve(args[1])
    if op == "put_on":
        _ensure_in_hand(world, x)
        world.set_pos(x, ("on", y.ident))
        return "put %s on %s" % (x.describe(), y.describe())

    raise IllegalAction("unknown operation %r" % op)
