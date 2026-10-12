"""Question generation (protocol §6, docs/develop/SHRDLU原始问句集.md §6.2).

Two ways of filling a question bank:

* **hand-written** — an entry in the scenario file carrying both the question
  and its semantics (:func:`shrdlu.questions.question_from_json`);
* **generated** — this module, which enumerates the questions that make sense
  against a given state and samples them reproducibly.

The hard constraint is protocol §2.1: a definite description must pick out
**exactly one** object.  Every candidate is therefore run through
:func:`shrdlu.questions.validate` and discarded unless it is clean, so a
generated bank can never contain an unanswerable question.

Sampling is stratified — by question shape and by whether the answer is yes or
no — so a bank is not all one kind and not all one answer.  That matters: a
testee that always says "no" must not score half marks.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .. import questions
from ..testee import nlp
from ..questions import AllQ, AttrQ, CountQ, Desc, ExistsQ, Question, Rel, RelQ
from .scenario import Scenario
from ..world import Obj, World

#: Question shapes, in the order they appear in a bank.
SHAPES = ("attr", "rel", "count", "exists", "all")

#: Attributes asked about, in preference order.
ATTRS = ("color", "size", "kind")


# --------------------------------------------------------------------------
# Building descriptions that actually pick something out
# --------------------------------------------------------------------------


def definite_descriptions(world: World) -> List[Desc]:
    """Every simple description that picks out exactly one object."""
    found: List[Desc] = []
    seen = set()
    for obj in world.actual_objects():
        for desc in _descriptions_for(world, obj):
            if desc in seen:
                continue
            if questions.validate_desc(desc, world) is not None:
                continue
            seen.add(desc)
            found.append(desc)
    return found


def _descriptions_for(world: World, obj: Obj) -> List[Desc]:
    """Candidate definite descriptions, shortest first."""
    out: List[Desc] = []
    if obj.color and obj.kind:
        out.append(Desc(quant="the", color=obj.color, kind=obj.kind))
    if obj.size and obj.color and obj.kind:
        out.append(Desc(quant="the", size=obj.size, color=obj.color, kind=obj.kind))
    if obj.kind:
        out.append(Desc(quant="the", kind=obj.kind))

    # a relational description: "the cube on the red cube"
    pos = world.pos_of(obj)
    for rel in _relation_of(world, obj, pos):
        if obj.color and obj.kind:
            out.append(Desc(quant="the", color=obj.color, kind=obj.kind, rels=(rel,)))
        if obj.kind:
            out.append(Desc(quant="the", kind=obj.kind, rels=(rel,)))
    return out


def _relation_of(world: World, obj: Obj, pos: Sequence[object]) -> List[Rel]:
    """A relation describing where ``obj`` is, if it is a describable one."""
    if pos[0] == "on":
        support = world.get(str(pos[1]))
        if support is None:
            return []
        target = _shortest_target(support)
        return [Rel("on", target)] if target else []
    return []


def _shortest_target(obj: Optional[Obj]) -> Optional[Desc]:
    """The briefest way to name an object used as a relation target.

    This is only used to *build* candidates; whether the resulting definite
    description is actually unique is decided later by ``validate``, which
    drops the ones that are not.
    """
    if obj is None:
        return None
    if obj.color:
        return Desc(quant="the", color=obj.color, kind=obj.kind)
    return Desc(quant="the", kind=obj.kind)


def plural_descriptions(world: World) -> List[Desc]:
    """Descriptions whose referent set is non-empty (for count/exists/all).

    The quantifier is left at the neutral ``"the"``: it is a surface detail
    that the parser normalises away, so emitting ``"all"`` here would make a
    generated question compare unequal to its own parse.
    """
    out: List[Desc] = []
    seen = set()
    kinds = sorted({o.kind for o in world.actual_objects()})
    colors = sorted({o.color for o in world.actual_objects() if o.color})
    sizes = sorted({o.size for o in world.actual_objects() if o.size})

    candidates: List[Desc] = []
    for kind in kinds:
        candidates.append(Desc(quant="the", kind=kind))
        for colour in colors:
            candidates.append(Desc(quant="the", color=colour, kind=kind))
        for size in sizes:
            candidates.append(Desc(quant="the", size=size, kind=kind))
        for other in definite_descriptions(world):
            candidates.append(Desc(quant="the", kind=kind, rels=(Rel("on", other),)))

    for desc in candidates:
        if desc in seen:
            continue
        if not questions.candidates(world, desc):
            continue
        seen.add(desc)
        out.append(desc)
    return out


def _unary_relations(world: World) -> List[Rel]:
    return [Rel("on_table"), Rel("clear"), Rel("supported")]


# --------------------------------------------------------------------------
# Enumerating candidates
# --------------------------------------------------------------------------


def is_unambiguous(question: Question) -> bool:
    """True when the English surface has exactly one reading in our grammar.

    Some perfectly good wordings bracket two ways.  "Is the green cube on the
    red cube on the table?" is either

        [the green cube on the red cube] on the table
        the green cube on [the red cube on the table]

    Both are valid English, so asking it would be unfair no matter which
    reading the grader used.  The parser is the only grammar oracle we have,
    so it is used here to reject such questions at authoring time.  This is a
    fairness check, not part of the judged protocol.
    """
    text = questions.render(question)
    try:
        return nlp.parse_question(text) == question
    except nlp.ParseError:
        return False


def shape_of(question: Question) -> str:
    if isinstance(question, AttrQ):
        return "attr"
    if isinstance(question, RelQ):
        return "rel"
    if isinstance(question, CountQ):
        return "count"
    if isinstance(question, ExistsQ):
        return "exists"
    return "all"


def candidates(world: World, shapes: Sequence[str] = SHAPES) -> List[Question]:
    """Every valid question this state supports, in a stable order."""
    out: List[Question] = []
    seen = set()

    def add(question: Question) -> None:
        if question in seen:
            return
        if questions.validate(question, world) is not None:
            return
        if not is_unambiguous(question):
            return
        seen.add(question)
        out.append(question)

    definites = definite_descriptions(world)
    plurals = plural_descriptions(world)

    if "attr" in shapes:
        for desc in definites:
            for attribute in ATTRS:
                add(AttrQ(desc, attribute))

    if "rel" in shapes:
        for desc in definites:
            for rel in _unary_relations(world):
                add(RelQ(desc, rel))
            for other in definites:
                if other == desc:
                    continue
                add(RelQ(desc, Rel("on", other)))

    if "count" in shapes or "exists" in shapes or "all" in shapes:
        for desc in plurals:
            for rel in _unary_relations(world):
                if "count" in shapes:
                    add(CountQ(desc, rel))
                if "exists" in shapes:
                    add(ExistsQ(desc, rel))
                if "all" in shapes:
                    add(AllQ(desc, rel))
            for other in definites:
                if "count" in shapes:
                    add(CountQ(desc, Rel("on", other)))
                if "exists" in shapes:
                    add(ExistsQ(desc, Rel("on", other)))
    return out


# --------------------------------------------------------------------------
# Sampling
# --------------------------------------------------------------------------


def generate(
    world: World,
    count: int = 10,
    seed: int = 0,
    shapes: Sequence[str] = SHAPES,
) -> List[Question]:
    """Sample ``count`` valid questions, reproducibly and with variety.

    Stratifies by (shape, answer), then round-robins across the strata so a
    bank contains a spread of kinds and of yes/no answers.
    """
    return stratified_sample(candidates(world, shapes), world, count, random.Random(seed))


def stratified_sample(
    pool: Sequence[Question],
    world: World,
    count: int,
    rng: random.Random,
) -> List[Question]:
    """Take ``count`` questions from ``pool``, spread across shapes and answers.

    Round-robins over (shape, answer) strata, so a draw is not all one kind of
    question and not all one answer.  That matters: a testee that always says
    "no" must not score half marks.
    """
    if count <= 0 or not pool:
        return []

    buckets: Dict[Tuple[str, str], List[Question]] = defaultdict(list)
    for question in pool:
        answer = questions.evaluate(question, world)
        buckets[(shape_of(question), answer.text())].append(question)

    keys = sorted(buckets)
    for key in keys:
        buckets[key].sort(key=lambda q: questions.render(q))
        rng.shuffle(buckets[key])

    picked: List[Question] = []
    index = 0
    while len(picked) < count:
        progressed = False
        for key in keys:
            bucket = buckets[key]
            if index < len(bucket):
                picked.append(bucket[index])
                progressed = True
                if len(picked) >= count:
                    break
        if not progressed:
            break
        index += 1
    return picked


def generate_for(
    scenario: Scenario,
    count: int = 10,
    seed: int = 0,
    shapes: Sequence[str] = SHAPES,
) -> List[Question]:
    """Generate a bank for a scenario, against its post-instruction state."""
    return generate(scenario.final_world(), count=count, seed=seed, shapes=shapes)


def scenario_with_bank(
    scenario: Scenario,
    count: int = 10,
    seed: int = 0,
    shapes: Sequence[str] = SHAPES,
) -> Scenario:
    """A copy of ``scenario`` whose question bank has been generated."""
    from dataclasses import replace

    world = scenario.final_world()
    bank = generate(world, count=count, seed=seed, shapes=shapes)
    return replace(
        scenario,
        questions=bank,
        question_text=[questions.render(q) for q in bank],
        question_answer=[questions.evaluate(q, world).text() for q in bank],
    )


def balance(questions_: Iterable[Question], world: World) -> Dict[str, int]:
    """A small report on what a bank contains, for auditing."""
    report: Dict[str, int] = defaultdict(int)
    for question in questions_:
        report["total"] += 1
        report["shape:%s" % shape_of(question)] += 1
        report["answer:%s" % questions.evaluate(question, world).text()] += 1
    return dict(sorted(report.items()))
