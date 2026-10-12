"""Scenario: the fixed input to one match.

A scenario is decided once, before the match starts, and contains

* the **initial state** (the world the testee is shown once),
* the **instruction sequence** both parties are meant to carry out,
* the **question bank** the env will ask from,

all in canonical JSON (see :mod:`shrdlu.snapshot` and :mod:`shrdlu.questions`).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .. import snapshot
from ..questions import Question, question_from_json, question_to_json
from ..world import World

#: Scenario data ships inside the package (``shrdlu/scenarios/``) and is the one
#: place it is read from, in a checkout and in an installed package alike.
_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO_DIRS = [os.path.join(_PACKAGE_DIR, "scenarios")]

#: The first place a scenario is looked for.
SCENARIO_DIR = SCENARIO_DIRS[0]


class ScenarioError(Exception):
    """Raised when a scenario file is missing or malformed."""


@dataclass
class Instruction:
    """One prescribed operation, with the surface text the env will send."""

    op: str
    args: Tuple[str, ...]
    legal: bool = True
    text: str = ""
    reason_contains: str = ""

    @classmethod
    def from_json(cls, data: Dict[str, object]) -> "Instruction":
        return cls(
            op=str(data["op"]),
            args=tuple(str(a) for a in data["args"]),  # type: ignore[arg-type]
            legal=bool(data.get("legal", True)),
            text=str(data.get("text", "")),
            reason_contains=str(data.get("reason_contains", "")),
        )


@dataclass
class Scenario:
    """A loaded scenario."""

    name: str
    description: str = ""
    state: Dict[str, object] = field(default_factory=dict)
    instructions: List[Instruction] = field(default_factory=list)
    questions: List[Question] = field(default_factory=list)
    #: Recorded surface text per question, used to assert the generator (§8.3).
    question_text: List[str] = field(default_factory=list)
    #: Recorded truth per question, used to assert the evaluator (§8.3).
    question_answer: List[str] = field(default_factory=list)
    expected_final_state: Optional[Dict[str, object]] = None
    #: Present when the scenario came out of the scene generator.
    generated: Optional[Dict[str, object]] = None

    def world(self) -> World:
        """A fresh world at the scenario's initial state."""
        return snapshot.from_snapshot(self.state)

    def final_world(self) -> World:
        """The world after the whole instruction sequence has been carried out.

        The truth follows the script, so illegal steps leave it unchanged.
        Questions are asked about *this* state.
        """
        from .. import ops  # local import keeps the module import order simple

        world = self.world()
        for step in self.instructions:
            if ops.check(world, step.op, list(step.args)).legal:
                ops.apply(world, step.op, list(step.args))
        return world


def find(name: str) -> Optional[str]:
    """The path of a scenario name, searching every known scenario directory."""
    for directory in SCENARIO_DIRS:
        candidate = os.path.join(directory, "%s.json" % name)
        if os.path.exists(candidate):
            return candidate
    return None


def load(name_or_path: str) -> Scenario:
    """Load a scenario by name (from ``shrdlu/scenarios/``) or by explicit path."""
    path = name_or_path
    if not os.path.isabs(path) and not path.endswith(".json"):
        found = find(name_or_path)
        if found is None:
            raise ScenarioError(
                "no such scenario: %s (looked in %s)"
                % (name_or_path, ", ".join(SCENARIO_DIRS))
            )
        path = found
    if not os.path.exists(path):
        raise ScenarioError("no such scenario: %s" % path)
    with open(path, "r", encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except ValueError as exc:
            raise ScenarioError("%s is not valid JSON: %s" % (path, exc))
    # The file's own "name" wins: a saved scenario keeps its identity whatever
    # the file happens to be called.
    fallback = os.path.splitext(os.path.basename(path))[0]
    return from_json(data, name=str(data.get("name") or fallback))


def from_json(data: Dict[str, object], name: str = "") -> Scenario:
    if "state" not in data:
        raise ScenarioError("scenario has no 'state'")
    questions: List[Question] = []
    texts: List[str] = []
    answers: List[str] = []
    for entry in data.get("questions") or []:  # type: ignore[union-attr]
        questions.append(question_from_json(entry))  # type: ignore[arg-type]
        texts.append(str(entry.get("text", "")))  # type: ignore[union-attr]
        answers.append(str(entry.get("answer", "")))  # type: ignore[union-attr]
    return Scenario(
        name=name or str(data.get("name", "scenario")),
        description=str(data.get("description", "")),
        state=dict(data["state"]),  # type: ignore[arg-type]
        instructions=[
            Instruction.from_json(step) for step in (data.get("instructions") or [])  # type: ignore[union-attr]
        ],
        questions=questions,
        question_text=texts,
        question_answer=answers,
        expected_final_state=(
            dict(data["expected_final_state"]) if data.get("expected_final_state") else None  # type: ignore[arg-type]
        ),
        generated=(
            dict(data["generated"]) if data.get("generated") else None  # type: ignore[arg-type]
        ),
    )


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------


def to_json(scenario_: Scenario) -> Dict[str, object]:
    """Serialise back to the file format, round-tripping :func:`from_json`."""
    out: Dict[str, object] = {
        "name": scenario_.name,
        "description": scenario_.description,
        "state": scenario_.state,
        "instructions": [
            {
                "op": step.op,
                "args": list(step.args),
                "legal": step.legal,
                "text": step.text,
                **({"reason_contains": step.reason_contains} if step.reason_contains else {}),
            }
            for step in scenario_.instructions
        ],
        "questions": [
            dict(question_to_json(question), text=text, answer=answer)
            for question, text, answer in zip(
                scenario_.questions, scenario_.question_text, scenario_.question_answer
            )
        ],
    }
    if scenario_.generated:
        out["generated"] = scenario_.generated
    if scenario_.expected_final_state:
        out["expected_final_state"] = scenario_.expected_final_state
    return out


def save(scenario_: Scenario, path: str) -> str:
    """Write a scenario to a file.  Returns the path written."""
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(to_json(scenario_), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path
