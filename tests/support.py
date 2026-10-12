"""Shared helpers for the test suite.

Scenario data lives in ``shrdlu/scenarios/*.json``, inside the package and
nowhere else: it is what the runner reads and what the wheel ships, so the tests
and the programs cannot drift apart over it.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCENARIO_DIR = os.path.join(ROOT, "shrdlu", "scenarios")

if ROOT not in os.sys.path:
    os.sys.path.insert(0, ROOT)

from shrdlu import ops, snapshot  # noqa: E402
from shrdlu.world import World  # noqa: E402

DEFAULT_SCENARIO = "first-version"


def load_scenario(name: str = DEFAULT_SCENARIO) -> Dict[str, object]:
    """Read a scenario file from ``shrdlu/scenarios/``."""
    path = os.path.join(SCENARIO_DIR, "%s.json" % name)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def scene_world(scenario: Optional[Dict[str, object]] = None) -> World:
    """The scenario's initial world."""
    data = scenario if scenario is not None else load_scenario()
    return snapshot.from_snapshot(data["state"])  # type: ignore[arg-type]


def apply_instructions(
    world: World, instructions: List[Dict[str, object]]
) -> List[Dict[str, object]]:
    """Run an instruction list, skipping the illegal ones.

    Returns the applied steps, so a test can assert on which ones took effect.
    """
    applied = []
    for step in instructions:
        verdict = ops.check(world, str(step["op"]), list(step["args"]))  # type: ignore[arg-type]
        if verdict.legal:
            ops.apply(world, str(step["op"]), list(step["args"]))  # type: ignore[arg-type]
            applied.append(step)
    return applied


def after_instructions(scenario: Optional[Dict[str, object]] = None) -> World:
    """The world after the scenario's full instruction sequence."""
    data = scenario if scenario is not None else load_scenario()
    world = scene_world(data)
    apply_instructions(world, data["instructions"])  # type: ignore[arg-type]
    return world
