"""Scene generation — making up new worlds to test against.

The env used to be able to play only hand-written scenarios.  This module
builds new ones: pick some objects, work out where they stand, and check that
the result is a *good* scene rather than merely a valid one.

"Good" is not a matter of taste here.  A scene is only worth testing against if

* it is **physically consistent** — nothing floats, nothing rests on a pyramid,
  containers only contain;
* it **supports a usable question bank** — several shapes of question, and both
  ``yes`` and ``no`` answers among them.  A scene where every answer is "yes"
  cannot tell a careful testee from one that agrees with everything;
* it **gives the instruction generator something to do** — at least one legal
  operation exists.

All three are mechanically checkable, so generation is: attempt, check, retry.
The seed alone fixes which scene comes out.

Only level 1 exists for now: few objects, shallow, nothing nested.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import asdict, dataclass, field
from itertools import count
from typing import Dict, List, Optional, Sequence, Tuple

from .. import ops, questions, snapshot
from . import generator, scenario
from ..world import SUPPORTING_KINDS, World, check_consistent



class SceneGenerationError(Exception):
    """Raised when no acceptable scene could be produced."""


@dataclass
class Spec:
    """What kind of scene to make.  Level 1 is the only level for now."""

    level: int = 1
    min_objects: int = 4
    max_objects: int = 6
    #: Cubes fill the scene; at most one pyramid and one ball, so the shapes
    #: stay varied without the scene getting crowded.  There is no ``box``: a
    #: box was only ever a container, and Level 1 has no containment.  ``ball``
    #: takes its place in the shape vocabulary — it was supported everywhere
    #: already (world, parser, answers, renderer) but never generated.
    max_pyramids: int = 1
    max_balls: int = 1
    colors: Tuple[str, ...] = ("red", "green", "blue", "yellow")
    min_distinct_colors: int = 2
    #: Colours the scene must contain.  A scene without either of these cannot
    #: show that a colour-confusion fault is wrong: the calibration variant in
    #: A testee that swaps blue and yellow runs into trouble against a scene holding
    #: neither it *passes*, which would quietly break the guarantee that every
    #: variant fails every generated exam.
    require_colors: Tuple[str, ...] = ("blue", "yellow")
    #: At least one big and one small object, so size questions discriminate.
    require_both_sizes: bool = True
    #: Every object must be uniquely nameable: no two share colour+size+kind.
    require_distinct_objects: bool = True
    #: Stacking: at most so tall, and how many stacks of two to aim for.
    max_stack_height: int = 2
    #: A stack should not balance something big on something smaller.
    stack_small_on_large: bool = True
    min_pairs: int = 1
    max_pairs: int = 1
    #: Nesting (objects inside containers) is a level-2 concern; Level 1 has no
    #: operation that could produce it, so there is nothing to switch off here.
    #: Quality thresholds for the bank the scene can support.
    min_shapes: int = 3
    require_yes_and_no: bool = True
    require_legal_operation: bool = True
    max_attempts: int = 300

    def as_json(self) -> Dict[str, object]:
        data = asdict(self)
        data["colors"] = list(self.colors)
        data["require_colors"] = list(self.require_colors)
        return data


@dataclass
class GeneratedScene:
    """A scene, plus how it was produced."""

    name: str
    seed: int
    attempts: int
    spec: Spec
    state: Dict[str, object]

    def world(self) -> World:
        return snapshot.from_snapshot(self.state)

    def as_json(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "generated": {
                "seed": self.seed,
                "attempts": self.attempts,
                "level": self.spec.level,
                "objects": len(self.state.get("objects", [])),  # type: ignore[arg-type]
                "spec": self.spec.as_json(),
            },
            "state": self.state,
            "instructions": [],
            "questions": [],
        }

    def summary(self) -> str:
        world = self.world()
        lines = [
            "%s  (seed %d, %d attempt%s)"
            % (self.name, self.seed, self.attempts, "" if self.attempts == 1 else "s"),
            "  objects:",
        ]
        for obj in world.actual_objects():
            pos = world.pos_of(obj)
            where = "on the table" if pos[0] == "table" else "on %s" % pos[1]
            lines.append("    %-14s %s %s %-8s %s" % (
                obj.ident, obj.size, obj.color, obj.kind, where))
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------


def generate(spec: Optional[Spec] = None, seed: int = 0,
             name: Optional[str] = None) -> GeneratedScene:
    """Produce a scene satisfying ``spec``, or raise.

    Deterministic in ``seed``: the same seed and spec always give the same
    scene, so a scene can be regenerated or, better, saved to a file.
    """
    spec = spec or Spec()
    for attempt in range(spec.max_attempts):
        rng = random.Random((seed << 16) ^ attempt ^ (spec.level << 28))
        state = _attempt(rng, spec)
        if not problems(state, spec):
            return GeneratedScene(
                name=name or "gen-l%d-%04d" % (spec.level, seed),
                seed=seed,
                attempts=attempt + 1,
                spec=spec,
                state=state,
            )
    raise SceneGenerationError(
        "no acceptable scene after %d attempts (seed %d, level %d)"
        % (spec.max_attempts, seed, spec.level)
    )


def _attempt(rng: random.Random, spec: Spec) -> Dict[str, object]:
    """One roll of the dice.  May produce a scene that fails the checks."""
    count = rng.randint(spec.min_objects, spec.max_objects)
    objects = _choose_objects(rng, spec, count)
    stacks = _arrange(rng, spec, objects)
    return _emit(spec, stacks)


def _choose_objects(rng: random.Random, spec: Spec, count: int) -> List[Dict[str, str]]:
    """Pick kinds, colours and sizes for ``count`` objects.

    Every object gets a distinct (colour, size, kind) triple when
    ``require_distinct_objects`` is set, so each one can be named uniquely —
    "the small green cube" must not be two different objects in a level-1
    scene, or a whole class of questions becomes unaskable.
    """
    kinds = _choose_kinds(rng, spec, count)
    assignment: List[Dict[str, str]] = []
    for _ in range(64):
        assignment = _assign_attributes(rng, spec, kinds)
        if _spread_ok(assignment, spec):
            return assignment
    return assignment  # best effort; the quality check will reject it


def _choose_kinds(rng: random.Random, spec: Spec, count: int) -> List[str]:
    """Cubes fill the scene; at most one pyramid and one ball sit among them."""
    kinds = ["cube"] * count
    spare = list(range(count))
    rng.shuffle(spare)
    if spec.max_pyramids:
        kinds[spare.pop()] = "pyramid"
    if spec.max_balls:
        kinds[spare.pop()] = "ball"
    return kinds


def _assign_attributes(
    rng: random.Random, spec: Spec, kinds: Sequence[str]
) -> List[Dict[str, str]]:
    used = set()
    out: List[Dict[str, str]] = []
    for kind in kinds:
        combos = [
            (colour, size)
            for colour in spec.colors
            for size in ("big", "small")
            if (colour, size, kind) not in used and (colour, size, kind) not in {
                (o["color"], o["size"], o["kind"]) for o in out
            }
        ]
        if not combos:
            combos = [(rng.choice(spec.colors), rng.choice(("big", "small")))]
        colour, size = rng.choice(combos)
        out.append({"kind": kind, "color": colour, "size": size})
    return out


def _spread_ok(objects: Sequence[Dict[str, str]], spec: Spec) -> bool:
    if len({o["color"] for o in objects}) < spec.min_distinct_colors:
        return False
    if spec.require_both_sizes and len({o["size"] for o in objects}) < 2:
        return False
    if spec.require_distinct_objects:
        triples = {(o["color"], o["size"], o["kind"]) for o in objects}
        if len(triples) != len(objects):
            return False
    return True


def _arrange(
    rng: random.Random, spec: Spec, objects: Sequence[Dict[str, str]]
) -> List[List[Dict[str, str]]]:
    """Group objects into stacks.  Where each stack stands is not decided here.

    The scene says what rests on what and nothing else; the picture chooses its
    own layout.  So there is no cell to sample, and no cell for a scene to
    disagree with the relations about.
    """
    remaining = list(objects)
    rng.shuffle(remaining)

    wanted_pairs = rng.randint(spec.min_pairs, spec.max_pairs) if spec.max_pairs else 0
    supporters = sum(1 for o in remaining if o["kind"] in SUPPORTING_KINDS)
    pairs = min(wanted_pairs, supporters, len(remaining) // 2)

    stacks: List[List[Dict[str, str]]] = []
    for _ in range(pairs):
        pair = _take_stackable_pair(remaining, spec)
        if pair is None:
            break
        stacks.append(list(pair))

    while remaining:
        picked = remaining.pop()
        stacks.append([picked])

    rng.shuffle(stacks)
    return stacks


#: Size order, so a stack can be checked for plausibility.
SIZE_RANK = {"small": 0, "big": 1}


def _take_stackable_pair(pool: List[Dict[str, str]], spec: Spec):
    """Remove and return a (bottom, top) pair that may plausibly be stacked."""
    for bottom_index, bottom in enumerate(pool):
        if bottom["kind"] not in SUPPORTING_KINDS:
            continue
        for top_index, top in enumerate(pool):
            if top_index == bottom_index:
                continue
            if spec.stack_small_on_large and SIZE_RANK[top["size"]] > SIZE_RANK[bottom["size"]]:
                continue
            # remove the later index first so the earlier one stays valid
            high, low = sorted((bottom_index, top_index), reverse=True)
            pool.pop(high)
            pool.pop(low)
            return bottom, top
    return None


def _emit(
    spec: Spec, stacks: Sequence[List[Dict[str, str]]]
) -> Dict[str, object]:
    """Turn the arrangement into the canonical snapshot form."""
    rows: List[Dict[str, object]] = []
    counter = count()

    for stack in stacks:
        below: Optional[str] = None
        for index, obj in enumerate(stack):
            ident = _ident(next(counter))
            pos: List[object] = ["table"] if index == 0 else ["on", below]
            rows.append({
                "id": ident,
                "kind": obj["kind"],
                "color": obj["color"],
                "size": obj["size"],
                "pos": pos,
            })
            below = ident

    # put the tallest stacks first: reads better, and makes the shape of the
    # scene obvious in the file
    rows.sort(key=lambda row: (row["pos"][0] != "table", str(row["id"])))
    return {"objects": rows, "hand": None}


#: Identifiers are short and carry no information about the object.
#: They are what gets drawn on the object and what a testee answers with, so a
#: descriptive id like "green-cube" would hand over attribute answers for free.
LABELS = "abcdefghijklmnopqrstuvwxyz"


def _ident(index: int) -> str:
    """The id for the nth object: ``a``, ``b``, ``c`` ..."""
    if index < len(LABELS):
        return LABELS[index]
    return "z%d" % index


# --------------------------------------------------------------------------
# Quality
# --------------------------------------------------------------------------


def problems(state: Dict[str, object], spec: Optional[Spec] = None) -> List[str]:
    """Everything wrong with a candidate scene; empty means acceptable."""
    spec = spec or Spec()
    out: List[str] = []
    try:
        world = snapshot.from_snapshot(state)
    except snapshot.SnapshotError as exc:
        return ["unreadable state: %s" % exc]

    out.extend(check_consistent(world))

    objects = world.actual_objects()
    if not spec.min_objects <= len(objects) <= spec.max_objects:
        out.append("object count %d outside %d..%d"
                   % (len(objects), spec.min_objects, spec.max_objects))

    if len({o.color for o in objects}) < spec.min_distinct_colors:
        out.append("fewer than %d distinct colours" % spec.min_distinct_colors)
    if spec.require_both_sizes and len({o.size for o in objects}) < 2:
        out.append("not both sizes present")
    if spec.require_distinct_objects:
        triples = {(o.color, o.size, o.kind) for o in objects}
        if len(triples) != len(objects):
            out.append("two objects share colour+size+kind, so neither is uniquely nameable")
    if sum(1 for o in objects if o.kind == "pyramid") > spec.max_pyramids:
        out.append("too many pyramids")
    if sum(1 for o in objects if o.kind == "ball") > spec.max_balls:
        out.append("too many balls")

    present = {o.color for o in objects}
    for colour in spec.require_colors:
        if colour not in present:
            out.append("no %s object, so a colour-confusion fault would go "
                       "undetected" % colour)

    if spec.stack_small_on_large:
        for obj in objects:
            support = world.support_of(obj)
            if support is None or support.is_fixed:
                continue
            if SIZE_RANK[obj.size] > SIZE_RANK[support.size]:
                out.append("%s (%s) rests on the smaller %s" % (obj.ident, obj.size, support.ident))

    height = max((world.height(o) + 1 for o in objects), default=0)
    if height > spec.max_stack_height:
        out.append("stack height %d exceeds %d" % (height, spec.max_stack_height))
    if spec.max_stack_height < 2 and spec.min_pairs:
        out.append("spec asks for stacking but forbids a stack")

    if spec.require_legal_operation and not ops.legal_operations(world):
        out.append("no legal operation is possible")

    out.extend(_bank_problems(world, spec))
    return out


def _bank_problems(world: World, spec: Spec) -> List[str]:
    """A scene is only useful if the questions it supports are any good."""
    pool = generator.candidates(world)
    if not pool:
        return ["supports no valid questions at all"]

    out: List[str] = []
    shapes = {generator.shape_of(q) for q in pool}
    if len(shapes) < spec.min_shapes:
        out.append("supports only %d question shape(s): %s"
                   % (len(shapes), ", ".join(sorted(shapes))))
    if spec.require_yes_and_no:
        answers = {questions.evaluate(q, world).text() for q in pool}
        if "yes" not in answers:
            out.append("every question would be answered 'no'")
        if "no" not in answers:
            out.append("every question would be answered 'yes'")
    return out


# --------------------------------------------------------------------------
# Persisting
# --------------------------------------------------------------------------


def to_scenario_json(scene: GeneratedScene) -> Dict[str, object]:
    return scene.as_json()


def to_scenario(scene: GeneratedScene, name: Optional[str] = None):
    """The generated scene as a :class:`shrdlu.scenario.Scenario`."""
    return scenario.from_json(scene.as_json(), name=name or scene.name)


def save(scene: GeneratedScene, path: str) -> str:
    """Write a scene as a scenario file.  Returns the path written."""
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(to_scenario_json(scene), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path
