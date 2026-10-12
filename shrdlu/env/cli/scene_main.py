"""``shrdlu-scene`` — make up new scenes to test against.

    python3 -m shrdlu.env.cli.scene_main --seed 1
    python3 -m shrdlu.env.cli.scene_main --seed 1 --out out/gen-l1-0001.json
    python3 -m shrdlu.env.cli.scene_main --seed 1-5 --out-dir out/generated
    python3 -m shrdlu.env.cli.scene_main --check shrdlu/scenarios/first-version.json

``--seed`` takes one seed, a range (``1-5``) or a list (``1,4,9``): one seed or
a batch is the same option.

A scene is written as an ordinary scenario file with empty instructions and an
empty question bank: the env can already play it as a question-only match, and
the instruction generator can fill it in later.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from ... import questions, settings
from .. import generator, scenario, worldgen


def build_parser(cfg: "settings.Settings" = None) -> argparse.ArgumentParser:
    cfg = cfg or settings.load("scene")
    parser = argparse.ArgumentParser(
        prog="shrdlu-scene",
        description="Generate blocks-world scenes (level 1) and check them. "
                    "Defaults come from %s." % settings.CONFIG_NAME,
    )
    parser.add_argument("--seed", default=None,
                        help="a seed, a range (1-5) or a list (1,4,9)")
    parser.add_argument("--out", default=None,
                        help="write a single scene to this path")
    parser.add_argument("--out-dir", default=cfg["out_dir"],
                        help="write one file per scene into this directory")
    parser.add_argument("--check", default=None,
                        help="instead of generating, check an existing scenario file")
    parser.add_argument("--quiet", action=argparse.BooleanOptionalAction,
                        default=cfg["quiet"],
                        help="print only the one-line verdict per scene")
    parser.set_defaults(cfg=cfg)          # the standing values, from shrdlu.ini
    return parser


def parse_seeds(text: Optional[str]) -> List[int]:
    """``None`` → seed 0; ``"3"`` → one seed; ``"1-5"`` → a range; ``"1,4,9"`` → a list."""
    if text is None:
        return [0]
    text = str(text).strip()
    if "-" in text and "," not in text:
        low, high = text.split("-", 1)
        return list(range(int(low), int(high) + 1))
    return [int(part) for part in text.split(",") if part.strip()]


def report(scene: worldgen.GeneratedScene) -> str:
    world = scene.world()
    pool = generator.candidates(world)
    shapes = sorted({generator.shape_of(q) for q in pool})
    answers = sorted({questions.evaluate(q, world).text() for q in pool})
    return "%s: %s | %d objects, %d valid questions, shapes=%s, answers=%s" % (
        scene.name,
        "ok",
        len(world.actual_objects()),
        len(pool),
        ",".join(shapes),
        ",".join(answers),
    )


def do_check(path: str) -> int:
    try:
        loaded = scenario.load(path)
    except scenario.ScenarioError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    spec = worldgen.Spec()
    problems = worldgen.problems(loaded.state, spec)
    if problems:
        print("%s: NOT ACCEPTABLE" % path)
        for problem in problems:
            print("  - %s" % problem)
        return 1
    print("%s: ok (%d objects)" % (path, len(loaded.state.get("objects", []))))  # type: ignore[arg-type]
    return 0


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except settings.SettingsError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    if args.check:
        return do_check(args.check)

    level = args.cfg["level"]
    if level != 1:
        print("error: only level 1 is implemented (asked for %d)" % level, file=sys.stderr)
        return 2

    spec = worldgen.Spec(level=level)
    exit_code = 0
    seeds = parse_seeds(args.seed)
    for seed in seeds:
        try:
            scene = worldgen.generate(spec, seed=seed)
        except worldgen.SceneGenerationError as exc:
            print("seed %d: FAILED (%s)" % (seed, exc), file=sys.stderr)
            exit_code = 1
            continue

        target = None
        if args.out and len(seeds) == 1:
            target = args.out
        elif args.out_dir:
            target = os.path.join(args.out_dir, "%s.json" % scene.name)

        if args.quiet:
            print(report(scene))
        else:
            print(scene.summary())
            print("    %s" % report(scene))
            print()

        if target:
            worldgen.save(scene, target)
            print("written to %s" % target)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
