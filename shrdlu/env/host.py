"""The env program: it runs one match and decides the verdict.

One match has **three stages** (README.md §4.2, protocol §5, §6):

1. **initial** — the question bank is asked about the state the testee was
   shown, before anything moves;
2. **operations** — the prescribed instructions are issued **one at a time**,
   each reply judged against the 2x2 table in §5.4, and after every one of them
   the env compares its **two** states: the one that follows the script and the
   one that follows the testee's calls;
3. **final** — the same bank is asked again, judged against the state the
   testee's own calls produced (and compared with the truth for the record).

Each stage reaches its own conclusion, so one wrong operation does not
invalidate the questions asked after it, and the record says *where* a match
went wrong instead of only that it did.

The truth always follows the **prescribed script**, never the testee's actions:
both parties are given the same operation requirements, so what *should* have
happened is fixed.  A wrong action by the testee is evidence about the testee,
not a change to the world.  The second state is the opposite side of the same
coin: it starts from the **true initial state** and then follows exactly what
the testee asked for, so it says what the testee's *calls* did, never what it
believed or how it kept its own account of the world.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Protocol, Sequence, Tuple

from .. import ops, protocol, questions, snapshot
from . import answers, commands, render
from ..questions import Question
from .scenario import Instruction, Scenario
from ..world import World

#: The three stages of one match, in the order they are played (§7).
STAGES = ("initial", "operations", "final")

#: Human-facing names, used by records, viewers and reports.
STAGE_LABELS = {
    "initial": "第一步（对初始状态的问句）",
    "operations": "第二步（操作）",
    "final": "第三步（对变化后状态的问句）",
}

#: The same stages, named as shortly as possible (tables, one-line summaries).
STAGE_SHORT = {"initial": "第一步", "operations": "第二步", "final": "第三步"}


class HostError(Exception):
    """Raised when a match cannot be played as asked."""


class Testee(Protocol):
    """Anything that can answer one protocol line with another.

    Implementations may be in-process (tests, development) or run as a separate
    program; the host only ever hands them text, so both work the same way.
    """

    def handle(self, message: str) -> str:
        ...


@dataclass
class Step:
    """One exchange in the match record."""

    kind: str          # "command" | "question"
    sent: str          # the English text the env sent
    expected: str      # what the testee should have done or said
    received: str      # a short description of what it actually did
    ok: bool
    note: str = ""
    stage: str = ""    # "initial" | "operations" | "final" ("" for ad-hoc probes)
    #: The answer the *truth* asks for, when it differs from ``expected``
    #: (only possible in the final stage, whose baseline is the second state).
    truth_expected: str = ""
    matches_truth: Optional[bool] = None
    #: For an instruction: how the two states differed after it, if they did.
    drift: str = ""

    def render(self) -> str:
        mark = "ok  " if self.ok else "FAIL"
        line = "%s %-8s %-46s | %s" % (mark, self.kind, self.sent, self.received)
        if not self.ok and self.note:
            line += "  <- %s" % self.note
        if self.truth_expected:
            line += "\n       (世界的当前状态是 %s；这一份是 %s)" % (
                self.truth_expected,
                "答对了" if self.matches_truth else "答错了",
            )
        if self.drift:
            line += "\n       (两份状态不一致: %s)" % self.drift
        return line


@dataclass
class StageResult:
    """The conclusion of one stage, kept apart from the other two (§7)."""

    name: str
    total: int = 0
    correct: int = 0
    verdict: str = "understood"
    reasons: List[str] = field(default_factory=list)
    #: Instruction index (1-based) after which the two states first differed.
    diverged_at: Optional[int] = None
    drift: List[str] = field(default_factory=list)

    @property
    def understood(self) -> bool:
        return self.verdict == "understood"

    @property
    def label(self) -> str:
        return STAGE_LABELS.get(self.name, self.name)

    def summary(self) -> str:
        text = "%s: %d/%d" % (self.label, self.correct, self.total)
        if self.diverged_at is not None:
            text += "，第 %d 个操作后两份状态不一致" % self.diverged_at
        return "%s -> %s" % (text, "理解" if self.understood else "不理解")

    def to_json(self) -> Dict[str, object]:
        return {
            "stage": self.name,
            "label": self.label,
            "verdict": self.verdict,
            "correct": self.correct,
            "total": self.total,
            "diverged_at": self.diverged_at,
            "drift": list(self.drift),
            "reasons": list(self.reasons),
        }


@dataclass
class StepEvent:
    """Handed to an observer after every exchange, so a match can be watched.

    Carries the live truth world and the testee object, which is what lets an
    interactive viewer show both sides of the story as it unfolds.
    """

    index: int
    phase: str            # "observe" | "instruction" | "question"
    step: Optional[Step]
    truth: World
    testee: Testee
    result: "MatchResult"
    #: The state the testee's calls have produced so far (the second state).
    #: ``None`` only for exchanges that happen outside a match.
    second: Optional[World] = None
    #: Which of the three stages this exchange belongs to ("" for the opening).
    stage: str = ""


@dataclass
class MatchResult:
    """The outcome of one match."""

    scenario: str
    verdict: str                      # "understood" | "not_understood"
    steps: List[Step] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    #: Set when the testee attempted an illegal action (§3.3 immediate verdict).
    illegal_attempt: Optional[str] = None
    final_state: Dict[str, object] = field(default_factory=dict)
    #: The state the testee's own calls produced (protocol §5).
    second_state: Dict[str, object] = field(default_factory=dict)
    #: Where those two final states disagree, if they do.
    final_drift: List[Tuple[str, str, str]] = field(default_factory=list)
    stages: Dict[str, StageResult] = field(default_factory=dict)
    #: Failures that belong to no stage (a broken pipe, an unreadable reply):
    #: they make the whole match unusable, not one stage wrong.
    protocol_errors: List[str] = field(default_factory=list)
    skipped_questions: List[str] = field(default_factory=list)

    @property
    def understood(self) -> bool:
        return self.verdict == "understood"

    @property
    def asked(self) -> List[Step]:
        return [s for s in self.steps if s.kind == "question"]

    @property
    def correct(self) -> int:
        return sum(1 for s in self.asked if s.ok)

    def stage(self, name: str) -> StageResult:
        """One stage's own conclusion."""
        return self.stages[name]

    def summary(self) -> str:
        parts = [self.stages[name].summary() for name in STAGES if name in self.stages]
        return "%s: %s, verdict=%s" % (
            self.scenario,
            "；".join(parts),
            self.verdict,
        )

    def render(self) -> str:
        lines = ["=== scenario: %s ===" % self.scenario]
        stage = None
        for step in self.steps:
            if step.stage and step.stage != stage:
                stage = step.stage
                lines.append("")
                lines.append("--- %s" % STAGE_LABELS.get(stage, stage))
            lines.append(step.render())
        for text in self.skipped_questions:
            lines.append("skip     (invalid question) %s" % text)
        lines.append("")
        lines.append("final state (following the script):")
        for row in self.final_state.get("objects", []):  # type: ignore[union-attr]
            lines.append("    %-14s %s %s %s  %s" % (
                row["id"], row["size"], row["color"], row["kind"], row["pos"],
            ))
        lines.append("")
        if self.final_drift:
            lines.append("final state (following the testee's calls):")
            for row in self.second_state.get("objects", []):  # type: ignore[union-attr]
                lines.append("    %-14s %s %s %s  %s" % (
                    row["id"], row["size"], row["color"], row["kind"], row["pos"],
                ))
        else:
            lines.append("final state (following the testee's calls): identical")
        lines.append("")
        for name in STAGES:
            if name in self.stages:
                lines.append(self.stages[name].summary())
        lines.append("")
        lines.append("verdict: %s" % self.verdict)
        for reason in self.reasons:
            lines.append("  reason: %s" % reason)
        return "\n".join(lines)

    def to_json(self) -> Dict[str, object]:
        return {
            "scenario": self.scenario,
            "verdict": self.verdict,
            "correct": self.correct,
            "asked": len(self.asked),
            "illegal_attempt": self.illegal_attempt,
            "reasons": list(self.reasons),
            "protocol_errors": list(self.protocol_errors),
            "skipped_questions": list(self.skipped_questions),
            "stages": {name: stage.to_json() for name, stage in self.stages.items()},
            "steps": [
                {
                    "kind": s.kind,
                    "stage": s.stage,
                    "sent": s.sent,
                    "expected": s.expected,
                    "truth_expected": s.truth_expected,
                    "matches_truth": s.matches_truth,
                    "received": s.received,
                    "ok": s.ok,
                    "note": s.note,
                    "drift": s.drift,
                }
                for s in self.steps
            ],
            "final_state": self.final_state,
            "second_state": self.second_state,
            "final_drift": [list(row) for row in self.final_drift],
        }


def run(
    scenario: Scenario,
    testee: Testee,
    on_step: Optional[Callable[["StepEvent"], None]] = None,
    observe: str = "state",
) -> MatchResult:
    """Play one full match — the three stages of §7 — and return the record.

    ``on_step``, when given, is called after every exchange — including the
    opening observation.  That is the hook an interactive viewer uses to pause
    between steps; it must not change the world or the result.

    ``observe`` says what the single opening message carries: ``"state"`` (the
    symbolic truth), ``"image"`` (a picture of it), or ``"both"``.  A testee
    that is meant to see must be run with ``"image"``: if the state rides along,
    its perception is not being tested at all.
    """
    if observe not in ("state", "image", "both"):
        raise HostError("observe must be state, image or both, not %r" % (observe,))

    try:
        truth = scenario.world()
        #: The second state: the true initial state, then whatever the testee's
        #: calls made of it.  Both states belong to the env; the testee is never
        #: shown either of them again, and its own account of the world is never
        #: read (需求记录 §8).
        second = scenario.world()
    except snapshot.SnapshotError as exc:
        raise HostError("cannot load this scenario: %s" % exc) from exc

    result = MatchResult(scenario=scenario.name, verdict="understood")
    result.stages = {name: StageResult(name=name) for name in STAGES}

    _send(testee, _observation(truth, observe), result)
    _notify(on_step, StepEvent(0, "observe", None, truth, testee, result,
                               second=second, stage=""))

    _run_questions(scenario, truth, second, testee, result, on_step, "initial")
    _run_instructions(scenario, truth, second, testee, result, on_step)
    _run_questions(scenario, truth, second, testee, result, on_step, "final")

    result.final_state = snapshot.to_snapshot(truth)
    result.second_state = snapshot.to_snapshot(second)
    result.final_drift = snapshot.differences(truth, second)
    _finalise(result)
    return result


def _finalise(result: MatchResult) -> None:
    """Give every stage its own verdict and the match its summary verdict."""
    for name in STAGES:
        stage = result.stages[name]
        clean = stage.correct == stage.total and not stage.reasons
        stage.verdict = "understood" if clean else "not_understood"
    clean = not result.protocol_errors and all(
        result.stages[name].understood for name in STAGES
    )
    result.verdict = "understood" if clean else "not_understood"


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------


def _observation(truth: World, observe: str) -> str:
    """Build the one opening message, with whatever it is allowed to carry."""
    state = snapshot.to_snapshot(truth) if observe in ("state", "both") else None
    picture: Optional[bytes] = None
    if observe in ("image", "both"):
        missing = render.uncovered(truth)
        if missing:
            raise HostError(
                "this scene cannot be shown as a picture: %s "
                "(the picture covers ids, shapes, colours, sizes and what rests "
                "on what, not %s)"
                % ("; ".join(missing), ", ".join(render.UNCOVERED))
            )
        try:
            picture = render.to_png_bytes(truth)
        except render.RenderError as exc:
            raise HostError(
                "cannot send a picture: %s (the image mode needs Pillow)" % exc
            ) from exc
    return protocol.observe(state=state, image=picture)


def _fail(result: MatchResult, stage: str, text: str) -> None:
    """Record one failure against one stage, or against the whole match.

    A stage keeps its own reasons, so a wrong operation cannot show up as a
    reason of the final stage.  With no stage (a broken pipe, a reply that is
    not even JSON) the failure belongs to no stage in particular and the match
    as a whole is unusable.
    """
    result.reasons.append(text)
    if stage in result.stages:
        result.stages[stage].reasons.append(text)
    else:
        result.protocol_errors.append(text)


def _send(testee: Testee, message: str, result: MatchResult,
          stage: str = "") -> Optional[str]:
    """Deliver a message; return the reply text, or ``None`` on protocol error."""
    try:
        return testee.handle(message)
    except Exception as exc:  # a misbehaving testee must not crash the env
        _fail(result, stage, "testee raised on %s: %s" % (message[:60], exc))
        return None


def _reply(testee: Testee, message: str, result: MatchResult,
           stage: str = "") -> Dict[str, object]:
    raw = _send(testee, message, result, stage)
    if raw is None:
        return {"type": "error"}
    try:
        return protocol.decode(raw)
    except protocol.ProtocolError as exc:
        _fail(result, stage, "bad reply (%s): %r" % (exc, raw[:60]))
        return {"type": "error"}


# --------------------------------------------------------------------------
# Instructions
# --------------------------------------------------------------------------


def _notify(on_step, event: StepEvent) -> None:
    if on_step is not None:
        on_step(event)


def _run_instructions(
    scenario: Scenario,
    truth: World,
    second: World,
    testee: Testee,
    result: MatchResult,
    on_step=None,
) -> None:
    """The second stage: every operation, then a comparison of the two states."""
    stage = result.stages["operations"]
    for index, instruction in enumerate(scenario.instructions, start=1):
        prescribed = ops.check(truth, instruction.op, list(instruction.args))
        text = commands.render_instruction(truth, instruction.op, list(instruction.args))
        reply = _reply(testee, protocol.command(text), result, "operations")

        ok, note, illegal = _judge_command(truth, instruction, reply)
        if not ok:
            _fail(result, "operations",
                  "instruction %r: %s" % (text, note or "wrong response"))
        if illegal and result.illegal_attempt is None:
            result.illegal_attempt = "%s (%s)" % (text, illegal)

        expected = "refuse" if not prescribed.legal else "%s%s" % (
            instruction.op, tuple(instruction.args),
        )
        step = Step(
            kind="command",
            sent=text,
            expected=expected,
            received=_describe_reply(reply),
            ok=ok,
            note=note,
            stage="operations",
        )
        result.steps.append(step)
        stage.total += 1
        if ok:
            stage.correct += 1

        # The truth follows the script, never the testee's behaviour.
        if prescribed.legal:
            ops.apply(truth, instruction.op, list(instruction.args))
        # The second state follows the testee's calls: the env applies what it
        # asked for, and refuses (as any env would) what is illegal there.
        _apply_call(second, reply)

        drift = snapshot.differences(truth, second)
        if drift:
            step.drift = "；".join(
                "%s 世界的当前状态 %s / 它的调用 %s" % (ident, mine, theirs)
                for ident, mine, theirs in drift
            )
            if stage.diverged_at is None:
                stage.diverged_at = index
            stage.drift.append("第 %d 个操作后：%s" % (index, step.drift))

        _notify(on_step, StepEvent(len(result.steps), "instruction", step,
                                   truth, testee, result, second=second,
                                   stage="operations"))


def _apply_call(world: World, reply: Dict[str, object]) -> None:
    """Carry the testee's own call out on the state its calls have produced.

    Illegal calls are refused here too — that is what an env does, and it keeps
    the second state a faithful record of *what the testee asked for*.  A
    refusal or a missing answer changes nothing.
    """
    if reply.get("type") != "action":
        return
    op = protocol.message_op(reply)
    args = protocol.message_args(reply)
    if ops.check(world, op, args).legal:
        ops.apply(world, op, args)


def _judge_command(
    truth: World, instruction: Instruction, reply: Dict[str, object]
) -> Tuple[bool, str, str]:
    """Apply the 2x2 table of protocol §5.4.

    Returns ``(ok, note, illegal_attempt_reason)``.
    """
    prescribed = ops.check(truth, instruction.op, list(instruction.args))
    rtype = reply.get("type")

    if prescribed.legal:
        if rtype == "refuse":
            return False, "refused a legal instruction", ""
        if rtype != "action":
            return False, "expected an action or a refusal", ""
        got_op = protocol.message_op(reply)
        got_args = protocol.message_args(reply)
        if (got_op, got_args) != (instruction.op, list(instruction.args)):
            verdict = ops.check(truth, got_op, got_args)
            if not verdict.legal:
                return False, "acted on an illegal operation: %s" % verdict.reason, str(verdict.reason)
            return False, "acted differently than instructed", ""
        return True, "", ""

    # the prescribed instruction is illegal, so the only correct reply is a refusal
    if rtype == "refuse":
        return True, "", ""
    if rtype == "action":
        return (
            False,
            "executed an illegal instruction",
            "executed an illegal instruction (%s)" % (prescribed.reason or ""),
        )
    return False, "expected an action or a refusal", ""


def _describe_reply(reply: Dict[str, object]) -> str:
    rtype = reply.get("type")
    if rtype == "action":
        return "action %s%s" % (protocol.message_op(reply), tuple(protocol.message_args(reply)))
    if rtype == "refuse":
        return "refuse"
    if rtype == "answer":
        return "answer %r" % protocol.message_text(reply)
    return "no valid reply"


# --------------------------------------------------------------------------
# Questions
# --------------------------------------------------------------------------


def _run_questions(
    scenario: Scenario,
    truth: World,
    second: World,
    testee: Testee,
    result: MatchResult,
    on_step=None,
    stage_name: str = "initial",
) -> None:
    """One question stage, judged against a baseline state.

    The baseline is the truth in the **first** stage (nothing has moved yet) and
    the state the testee's own calls produced in the **third** (so an operation
    it got wrong does not make its later answers meaningless).  In that third
    stage the truth's own answer is recorded beside it, for the record — but it
    is the testee's state that decides whether the answer was right.
    """
    stage = result.stages[stage_name]
    for question in scenario.questions:
        text = questions.render(question)
        invalid = questions.validate(question, second)
        if invalid:
            # Protocol §6: invalid questions are dropped, never counted.  A
            # question can be askable in one stage and not in another — one
            # about a stack the instructions build has nothing to refer to
            # before they run — so the stage is named here.
            result.skipped_questions.append(
                "[%s] %s  (%s)" % (STAGE_SHORT.get(stage_name, stage_name), text, invalid))
            continue

        expected = questions.evaluate(question, second)
        truth_expected = questions.evaluate(question, truth)
        reply = _reply(testee, protocol.question(text), result, stage_name)
        given: Optional[str] = None
        if reply.get("type") == "answer":
            given = protocol.message_text(reply)
            ok = answers.matches(given, expected)
            note = "" if ok else "expected %s" % expected.text()
            received = "answer %r" % given
        else:
            ok = False
            note = "expected %s" % expected.text()
            received = _describe_reply(reply)

        step = Step(
            kind="question",
            sent=text,
            expected=expected.text(),
            received=received,
            ok=ok,
            note=note,
            stage=stage_name,
        )
        if truth_expected.text() != expected.text():
            step.truth_expected = truth_expected.text()
            step.matches_truth = (
                given is not None and answers.matches(given, truth_expected)
            )
        result.steps.append(step)
        stage.total += 1
        if ok:
            stage.correct += 1
        else:
            _fail(result, stage_name,
                  "question %r: answered %s" % (text, note or "wrongly"))

        _notify(on_step, StepEvent(len(result.steps), "question", step,
                                   truth, testee, result, second=second,
                                   stage=stage_name))


# --------------------------------------------------------------------------
# Ad-hoc probes, for an interactive observer
# --------------------------------------------------------------------------


def ask_question(
    truth: World,
    testee: Testee,
    result: MatchResult,
    question: Question,
    text: Optional[str] = None,
) -> Step:
    """Put one question to the testee outside the scripted bank.

    The exchange is returned but **not** added to the match record: the verdict
    is about the exam, and an operator poking at the testee must not change it.
    """
    text = text if text is not None else questions.render(question)
    expected = questions.evaluate(question, truth)
    reply = _reply(testee, protocol.question(text), result)
    if reply.get("type") == "answer":
        given = protocol.message_text(reply)
        ok = answers.matches(given, expected)
        return Step("question", text, expected.text(), "answer %r" % given, ok,
                    "" if ok else "expected %s" % expected.text())
    return Step("question", text, expected.text(), _describe_reply(reply), False,
                "expected %s" % expected.text())


def issue_instruction(
    truth: World,
    testee: Testee,
    result: MatchResult,
    op: str,
    args: Sequence[str],
    text: Optional[str] = None,
    second: Optional[World] = None,
) -> Step:
    """Issue one instruction outside the script and judge it the usual way.

    Unlike :func:`ask_question` this **does** change the world when the
    instruction is legal — an operator driving the match is acting as the env,
    so the scripted steps that follow are judged against the new state.

    ``second``, when given, is moved the same way (by the testee's own call), so
    an operator's interference does not silently desynchronise the two states
    the env compares afterwards.
    """
    args = [str(a) for a in args]
    text = text if text is not None else commands.render_instruction(truth, op, args)
    prescribed = ops.check(truth, op, args)
    instruction = Instruction(op=op, args=tuple(args), legal=prescribed.legal, text=text)
    reply = _reply(testee, protocol.command(text), result)
    ok, note, illegal = _judge_command(truth, instruction, reply)

    step = Step("command", text,
                "refuse" if not prescribed.legal else "%s%s" % (op, tuple(args)),
                _describe_reply(reply), ok,
                note if ok else (illegal or note))
    if prescribed.legal:
        ops.apply(truth, op, args)
    if second is not None:
        _apply_call(second, reply)
    return step
