"""``shrdlu-exam`` — write the instructions and questions for a scene.

    python3 -m shrdlu.env.cli.exam_main --scene out/gen-l1-0003.json --seed 1
    python3 -m shrdlu.env.cli.exam_main --seed 3 --out exam.json
    python3 -m shrdlu.env.cli.exam_main --check exam.json

A scene alone is not an exam: without instructions, the initial and final
states are identical and every question can be answered from the single
observation the testee was given.  This program adds the two missing halves —
an instruction sequence that creates change, and a question bank about the
result — and keeps the instruction sequence that makes the most questions
depend on having understood it.
"""

from __future__ import annotations

import argparse
import sys
from typing import List

from ... import questions, settings
from .. import authoring, generator, host, scenario, worldgen


def build_parser(cfg: "settings.Settings" = None) -> argparse.ArgumentParser:
    cfg = cfg or settings.load("exam")
    parser = argparse.ArgumentParser(
        prog="shrdlu-exam",
        description="Write an instruction sequence and a question bank for a scene. "
                    "Defaults come from %s." % settings.CONFIG_NAME,
    )
    parser.add_argument("--scene", default=cfg["scene"],
                        help="a scene (scenario) file to write an exam for")
    parser.add_argument("--seed", type=int, default=cfg["seed"],
                        help="seed; also used to generate a scene when --scene is absent")
    parser.add_argument("--steps", type=int, default=cfg["steps"],
                        help="exact number of instructions (default: 3 or 4)")
    parser.add_argument("--illegal", type=int, default=cfg["illegal"],
                        help="how many of the instructions should be impossible")
    parser.add_argument("--questions", type=int, default=cfg["questions"],
                        help="how many questions to ask")
    parser.add_argument("--out", default=cfg["out"],
                        help="write the finished scenario to this path")
    parser.add_argument("--check", default=None,
                        help="instead of writing, validate an existing exam file")
    parser.add_argument("--play", action="store_true",
                        help="also run a match in-process to prove it is playable")
    parser.add_argument("--quiet", action=argparse.BooleanOptionalAction,
                        default=cfg["quiet"],
                        help="print only the summary")
    parser.set_defaults(cfg=cfg)          # the standing values, from shrdlu.ini
    return parser


def build_spec(args) -> authoring.ExamSpec:
    steps = args.steps
    spec = authoring.ExamSpec(
        illegal_steps=max(0, args.illegal),
        questions=args.questions,
        min_reasoning_ratio=args.cfg["reasoning_ratio"],
    )
    if steps is not None:
        spec.min_steps = steps
        spec.max_steps = steps
    return spec


def do_check(path: str, spec: authoring.ExamSpec) -> int:
    try:
        loaded = scenario.load(path)
    except scenario.ScenarioError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    problems = authoring.exam_problems(loaded, spec)
    if problems:
        print("%s: NOT SOUND" % path)
        for problem in problems:
            print("  - %s" % problem)
        return 1
    print("%s: ok (%d instructions, %d questions)"
          % (path, len(loaded.instructions), len(loaded.questions)))
    return 0


def report(scenario_, exam: authoring.Exam) -> str:
    return "%s: %s" % (scenario_.name, exam.summary())


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except settings.SettingsError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    spec = build_spec(args)

    if args.check:
        return do_check(args.check, spec)

    scene_name = None
    generated = None
    if args.scene:
        try:
            loaded = scenario.load(args.scene)
        except scenario.ScenarioError as exc:
            print("error: %s" % exc, file=sys.stderr)
            return 2
        state = loaded.state
        scene_name = loaded.name
        generated = loaded.generated
    else:
        scene = worldgen.generate(worldgen.Spec(level=spec.level), seed=args.seed)
        state = scene.state
        scene_name = scene.name
        generated = scene.as_json()["generated"]

    try:
        written, exam = authoring.author(state, scene_name, spec=spec,
                                         seed=args.seed, generated=generated)
    except authoring.AuthoringError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1

    if args.quiet:
        print(report(written, exam))
    else:
        print("=== scene: %s ===" % scene_name)
        for obj in written.world().actual_objects():
            world = written.world()
            pos = world.pos_of(obj)
            where = "the table" if pos[0] == "table" else str(pos[1])
            print("    %-14s %s %s %-8s on %s" % (
                obj.ident, obj.size, obj.color, obj.kind, where))
        print()
        print("=== instructions ===")
        for index, step in enumerate(written.instructions, 1):
            tag = "ok    " if step.legal else "illegal"
            print("  %d. %s %-46s %s" % (
                index, tag, step.text,
                "" if step.legal else "(should be refused: %s)" % step.reason_contains))
        print()
        print("=== questions ===")
        initial, final = written.world(), written.final_world()
        for index, question in enumerate(written.questions, 1):
            reasoning = authoring.is_discriminating(question, initial, final)
            print("  %2d. [%s] %-48s -> %s" % (
                index, "reason" if reasoning else "recall",
                questions.render(question),
                questions.evaluate(question, final).text()))
        print()
        print(report(written, exam))

    if args.play:
        result = host.run(written, testee.make_testee())
        print("\nplayed: %s" % result.summary())

    if args.out:
        scenario.save(written, args.out)
        if not args.quiet:
            print("written to %s" % args.out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
