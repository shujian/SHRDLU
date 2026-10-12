"""Authoring — filling a scene with instructions and questions.

A scene on its own is not an exam.  Two more things are needed, and they are
**strictly ordered**:

    initial state --(instructions: create change)--> final state --(questions)-->

The order is not an implementation detail.  A question whose answer is the same
before and after the instructions can be answered from the single observation
the testee was handed, without ever reasoning about what its own actions did.
Such a question tests perception.  Only a question whose answer *changed* — or
which cannot even be asked of the initial state — forces the testee to have
worked out the consequences.  So:

* instructions exist to **create change**;
* questions are asked about the **result**;
* the quality of a question is judged by **whether the instructions mattered**.

That last point couples the two halves: a better instruction sequence is one
that makes more questions discriminating.  This module therefore tries several
sequences and keeps the one that supports the strongest bank.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .. import ops, questions, snapshot
from . import commands, generator, scenario, worldgen
from ..questions import Question
from .scenario import Instruction, Scenario
from ..world import World

#: The scenario used when a run names none.
DEFAULT_SCENARIO = "first-version"


def load_exam(
    name: Optional[str] = None,
    seed: Optional[int] = None,
    questions_count: int = 0,
    shapes: Optional[Sequence[str]] = None,
) -> Scenario:
    """The exam one run should play.

    * ``name`` given → that scenario (its bank is regenerated when
      ``questions_count`` > 0, from ``seed``);
    * no name and ``questions_count`` > 0 → the default scenario, bank regenerated;
    * no name, no questions, ``seed`` given → a whole scene+exam made from the seed;
    * neither → the default scenario as it stands.

    This is the single place the three host programs turn their ``--scenario`` /
    ``--seed`` / ``--questions`` options into something playable, so they cannot
    drift apart.
    """
    if name is None and questions_count <= 0 and seed is not None:
        scene = worldgen.generate(worldgen.Spec(), seed=seed)
        loaded, _ = author(scene.state, scene.name, seed=seed,
                           generated=scene.as_json()["generated"])
        return loaded

    loaded = scenario.load(name or DEFAULT_SCENARIO)
    if questions_count > 0:
        loaded = generator.scenario_with_bank(
            loaded,
            count=questions_count,
            seed=seed or 0,
            shapes=tuple(shapes) if shapes else generator.SHAPES,
        )
    return loaded


class AuthoringError(Exception):
    """Raised when no acceptable exam could be produced."""


# --------------------------------------------------------------------------
# Spec
# --------------------------------------------------------------------------


@dataclass
class ExamSpec:
    """What kind of exam to write.  Level 1 only, for now."""

    level: int = 1
    #: Instructions.  Level 1 is short, mostly legal, with one trap in it.
    min_steps: int = 3
    max_steps: int = 4
    illegal_steps: int = 1
    #: How much of the final state must differ from the initial one.
    min_changed_objects: int = 1
    #: Questions.
    questions: int = 10
    #: The share of the bank that must require reasoning rather than recall.
    min_reasoning_ratio: float = 0.5
    shapes: Tuple[str, ...] = generator.SHAPES
    #: How many instruction sequences to try, and on how many of the most
    #: promising ones to spend an exact (and much more costly) count.
    instruction_candidates: int = 24
    exact_candidates: int = 3
    max_attempts: int = 200

    def as_json(self) -> Dict[str, object]:
        return {
            "level": self.level,
            "min_steps": self.min_steps,
            "max_steps": self.max_steps,
            "illegal_steps": self.illegal_steps,
            "questions": self.questions,
            "min_reasoning_ratio": self.min_reasoning_ratio,
            "shapes": list(self.shapes),
        }


@dataclass
class Exam:
    """Instructions and questions for one scenario."""

    instructions: List[Instruction] = field(default_factory=list)
    questions: List[Question] = field(default_factory=list)
    seed: int = 0
    #: How many of the bank require reasoning (see :func:`is_discriminating`).
    reasoning: int = 0
    #: Candidates available in the final state, for the record.
    pool_size: int = 0
    reasoning_pool: int = 0
    sequence_attempts: int = 0

    @property
    def total(self) -> int:
        return len(self.questions)

    @property
    def reasoning_ratio(self) -> float:
        return (self.reasoning / self.total) if self.total else 0.0

    def summary(self) -> str:
        return (
            "%d instructions (%d illegal), %d questions, %d reasoning (%.0f%%), "
            "pool %d of which %d reasoning"
            % (
                len(self.instructions),
                sum(1 for i in self.instructions if not i.legal),
                self.total,
                self.reasoning,
                100 * self.reasoning_ratio,
                self.pool_size,
                self.reasoning_pool,
            )
        )


# --------------------------------------------------------------------------
# Is a question about reasoning or about recall?
# --------------------------------------------------------------------------


def is_discriminating(question: Question, initial: World, final: World) -> bool:
    """True when answering needs the instructions to have been understood.

    Either the answer differs between the two states, or the question cannot
    even be asked of the initial state (the object it names only comes into
    being as a description once the instructions have been carried out).
    """
    try:
        before = questions.evaluate(question, initial).text()
    except questions.QuestionError:
        return True
    return before != questions.evaluate(question, final).text()


def split_pool(
    pool: Sequence[Question], initial: World, final: World
) -> Tuple[List[Question], List[Question]]:
    """``(must_reason, replayable)``."""
    reasoning: List[Question] = []
    replayable: List[Question] = []
    for question in pool:
        (reasoning if is_discriminating(question, initial, final) else replayable).append(question)
    return reasoning, replayable


# --------------------------------------------------------------------------
# Instructions
# --------------------------------------------------------------------------


def generate_instructions(
    initial: World, spec: ExamSpec, rng: random.Random
) -> Optional[List[Instruction]]:
    """A short sequence of instructions, mostly legal, including a trap.

    The illegal step is chosen from traps that *follow from the state the
    instructions produced* — "pick up the cube that now has something on it",
    "put it on the pyramid".  They are only real traps if the testee has been
    tracking what happened, which is the point.
    """
    steps = rng.randint(spec.min_steps, spec.max_steps)
    if steps <= 0:
        return None
    illegal = min(spec.illegal_steps, steps)

    # The trap goes somewhere other than first, so there is context for it.
    positions = sorted(rng.sample(range(1, steps), min(illegal, steps - 1))) if steps > 1 else []
    if len(positions) < illegal:
        return None

    world = snapshot.from_snapshot(snapshot.to_snapshot(initial))
    instructions: List[Instruction] = []
    for index in range(steps):
        if index in positions:
            trap = _trap(rng, world)
            if trap is None:
                return None
            op, args, reason = trap
        else:
            legal = _pick_legal(rng, world)
            if legal is None:
                return None
            op, args = legal
            reason = ""

        verdict = ops.check(world, op, list(args))
        if index in positions and verdict.legal:
            return None  # it stopped being a trap
        if index not in positions and not verdict.legal:
            return None

        text = commands.render_instruction(world, op, list(args))
        instructions.append(
            Instruction(
                op=op,
                args=tuple(args),
                legal=verdict.legal,
                text=text,
                reason_contains=reason,
            )
        )
        # the world follows the script, exactly as it will during the match
        if verdict.legal:
            ops.apply(world, op, list(args))

    if _changed_objects(initial, world) < spec.min_changed_objects:
        return None
    return instructions


def _pick_legal(rng: random.Random, world: World
                ) -> Optional[Tuple[str, Tuple[str, ...]]]:
    """A legal instruction, biased towards ones that move things around."""
    legal = ops.legal_operations(world)
    if not legal:
        return None
    relational = [step for step in legal if step[0] == "put_on"]
    if relational and rng.random() < 0.75:
        return rng.choice(relational)
    return rng.choice(legal)


def _trap(rng: random.Random, world: World
          ) -> Optional[Tuple[str, Tuple[str, ...], str]]:
    """An illegal instruction that a testee which tracked the state should refuse."""
    traps: List[Tuple[str, Tuple[str, ...], str]] = []
    objects = world.actual_objects()

    # something is stacked on it, so it cannot be picked up
    for obj in objects:
        if world.height(obj) > 0 and not obj.held:
            verdict = ops.check(world, "pick_up", [obj.ident])
            if not verdict.legal and verdict.reason:
                traps.append(("pick_up", (obj.ident,), _key_of(verdict.reason)))

    # a pyramid cannot carry anything
    for pyramid in [o for o in objects if o.kind == "pyramid"]:
        for other in objects:
            if other.ident == pyramid.ident:
                continue
            verdict = ops.check(world, "put_on", [other.ident, pyramid.ident])
            if not verdict.legal and verdict.reason:
                traps.append(("put_on", (other.ident, pyramid.ident), _key_of(verdict.reason)))

    if not traps:
        return None
    return rng.choice(traps)


def _key_of(reason: str) -> str:
    """A stable fragment of a refusal reason, for the scenario's assertion."""
    for key in ("not clear", "cannot support", "not empty", "inside"):
        if key in reason:
            return key
    return reason


def _changed_objects(initial: World, final: World) -> int:
    """How many objects ended up somewhere different."""
    before = {row["id"]: row["pos"] for row in snapshot.to_snapshot(initial)["objects"]}  # type: ignore[index]
    after = {row["id"]: row["pos"] for row in snapshot.to_snapshot(final)["objects"]}  # type: ignore[index]
    return sum(1 for ident, pos in after.items() if before.get(ident) != pos)


def apply_instructions(initial: World, instructions: Sequence[Instruction]) -> World:
    """The world after the script, mirroring what the env will do."""
    world = snapshot.from_snapshot(snapshot.to_snapshot(initial))
    for step in instructions:
        if ops.check(world, step.op, list(step.args)).legal:
            ops.apply(world, step.op, list(step.args))
    return world


# --------------------------------------------------------------------------
# The whole exam
# --------------------------------------------------------------------------


def write_exam(state: Dict[str, object], spec: Optional[ExamSpec] = None,
               seed: int = 0) -> Exam:
    """Choose instructions and build a bank that makes the instructions matter.

    Several instruction sequences are tried; the one supporting the most
    reasoning questions wins.  This is the coupling described in the module
    docstring, made concrete.
    """
    spec = spec or ExamSpec()
    initial = snapshot.from_snapshot(state)

    # Stage one: a proxy that costs nothing ranks every candidate sequence.
    # Counting the real thing means enumerating (and parsing) every question
    # the final state supports, which is far too slow to do 24 times.
    proposals = []
    for attempt in range(spec.instruction_candidates):
        rng = random.Random((seed << 12) ^ attempt ^ (spec.level << 24))
        instructions = generate_instructions(initial, spec, rng)
        if instructions is None:
            continue
        final = apply_instructions(initial, instructions)
        proposals.append((richness(initial, final), attempt + 1, instructions, final))

    if not proposals:
        raise AuthoringError(
            "could not write an exam for this scene (seed %d): no usable "
            "instruction sequence in %d tries" % (seed, spec.instruction_candidates)
        )

    # Stage two: count exactly, but only on the few that look best.
    proposals.sort(key=lambda item: -item[0])
    best: Optional[Tuple[int, int, List[Instruction], World, int, int]] = None
    for _, attempt, instructions, final in proposals[: max(1, spec.exact_candidates)]:
        pool = generator.candidates(final, spec.shapes)
        if not pool:
            continue
        reasoning, _ = split_pool(pool, initial, final)
        if best is None or len(reasoning) > best[0]:
            best = (len(reasoning), attempt, instructions, final, len(pool), len(reasoning))

    if best is None:
        raise AuthoringError(
            "could not write an exam for this scene (seed %d): the candidate "
            "states support no questions" % seed
        )

    reasoning_pool, attempts, instructions, final, pool_size, _ = best
    rng = random.Random((seed << 8) ^ 0x5EED)
    bank, reasoning_count = build_bank(initial, final, spec, rng, pool_size)
    return Exam(
        instructions=list(instructions),
        questions=bank,
        seed=seed,
        reasoning=reasoning_count,
        pool_size=pool_size,
        reasoning_pool=reasoning_pool,
        sequence_attempts=attempts,
    )


def richness(initial: World, final: World) -> int:
    """A cheap stand-in for "how many questions will need reasoning".

    Counts how much moved, and how many objects ended up in a relation at all
    (each of those supports descriptions that simply cannot be formed from the
    initial state).  Measured against the exact count on real sequences, this
    ranks them almost identically — good enough to choose three finalists.
    """
    changed = _changed_objects(initial, final)
    relational = sum(1 for o in final.actual_objects() if final.pos_of(o)[0] in ("on", "in"))
    return changed * 4 + relational


def build_bank(
    initial: World,
    final: World,
    spec: ExamSpec,
    rng: random.Random,
    pool_size: int = 0,
) -> Tuple[List[Question], int]:
    """Fill the reasoning quota first, then top up for coverage."""
    pool = generator.candidates(final, spec.shapes)
    reasoning, replayable = split_pool(pool, initial, final)

    wanted = min(len(reasoning), math.ceil(spec.questions * spec.min_reasoning_ratio))
    picked = generator.stratified_sample(reasoning, final, wanted, rng)
    shortfall = spec.questions - len(picked)
    if shortfall > 0:
        picked += generator.stratified_sample(replayable, final, shortfall, rng)

    # keep the ordering stable and readable: reasoning first, then by text
    picked.sort(key=lambda q: (q not in reasoning, questions.render(q)))
    return picked, sum(1 for q in picked if q in reasoning)


def to_scenario(
    scene_name: str,
    state: Dict[str, object],
    exam: Exam,
    initial: Optional[World] = None,
    generated: Optional[Dict[str, object]] = None,
    spec: Optional[ExamSpec] = None,
) -> Scenario:
    """Assemble a playable scenario from a scene and an exam."""
    spec = spec or ExamSpec()
    world = initial if initial is not None else snapshot.from_snapshot(state)
    final = apply_instructions(world, exam.instructions)
    return Scenario(
        name=scene_name,
        description="generated level-%d exam" % spec.level,
        state=state,
        instructions=list(exam.instructions),
        questions=list(exam.questions),
        question_text=[questions.render(q) for q in exam.questions],
        question_answer=[questions.evaluate(q, final).text() for q in exam.questions],
        expected_final_state=snapshot.to_snapshot(final),
        generated=dict(generated or {}),
    )


def author(
    state: Dict[str, object],
    scene_name: str = "generated",
    spec: Optional[ExamSpec] = None,
    seed: int = 0,
    generated: Optional[Dict[str, object]] = None,
) -> Tuple[Scenario, Exam]:
    """Scene state in, playable scenario out."""
    spec = spec or ExamSpec()
    exam = write_exam(state, spec=spec, seed=seed)
    world = snapshot.from_snapshot(state)
    scenario_ = to_scenario(scene_name, state, exam, initial=world,
                            generated=generated, spec=spec)
    if scenario_.generated is not None:
        scenario_.generated["exam"] = {
            "seed": seed,
            "reasoning_pool": exam.reasoning_pool,
            "pool_size": exam.pool_size,
            "sequence_attempts": exam.sequence_attempts,
            "spec": spec.as_json(),
        }
    return scenario_, exam


# --------------------------------------------------------------------------
# Checking a written exam
# --------------------------------------------------------------------------


def exam_problems(scenario_: Scenario, spec: Optional[ExamSpec] = None) -> List[str]:
    """Everything wrong with a written exam; empty means it is sound.

    Checks that the recorded English and the recorded answers still agree with
    the generator and the evaluator, and that the bank really does contain the
    promised share of reasoning questions.  A written exam is an artefact: it
    outlives the code that produced it, so it has to be checked, not trusted.
    """
    spec = spec or ExamSpec()
    out: List[str] = []

    initial = scenario_.world()
    world = snapshot.from_snapshot(snapshot.to_snapshot(initial))
    for step in scenario_.instructions:
        verdict = ops.check(world, step.op, list(step.args))
        if verdict.legal != step.legal:
            out.append(
                "instruction %r: it is %s but the exam records it as %s"
                % (step.op, "legal" if verdict.legal else "illegal",
                   "legal" if step.legal else "illegal")
            )
        rendered = commands.render_instruction(world, step.op, list(step.args))
        if step.text and step.text != rendered:
            out.append("instruction text mismatch: %r vs %r" % (step.text, rendered))
        if not step.legal and step.reason_contains:
            if step.reason_contains not in (verdict.reason or ""):
                out.append(
                    "instruction %r is illegal for %r, not %r"
                    % (step.op, verdict.reason, step.reason_contains)
                )
        if verdict.legal:
            ops.apply(world, step.op, list(step.args))

    for question, text, answer in zip(
        scenario_.questions, scenario_.question_text, scenario_.question_answer
    ):
        rendered = questions.render(question)
        if text and text != rendered:
            out.append("question text mismatch: %r vs %r" % (text, rendered))
        try:
            truth = questions.evaluate(question, world).text()
        except questions.QuestionError as exc:
            out.append("question %r cannot be evaluated: %s" % (rendered, exc))
            continue
        if answer and truth != answer:
            out.append("question %r: recorded %r but the truth is %r"
                       % (rendered, answer, truth))

    if scenario_.questions:
        reasoning = sum(
            1 for q in scenario_.questions if is_discriminating(q, initial, world)
        )
        ratio = reasoning / len(scenario_.questions)
        if ratio + 1e-9 < spec.min_reasoning_ratio:
            out.append(
                "only %.0f%% of the bank needs reasoning, wanted %.0f%%"
                % (100 * ratio, 100 * spec.min_reasoning_ratio)
            )
    return out
