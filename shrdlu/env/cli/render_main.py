"""``shrdlu-render`` — draw a scene as a picture.

    python3 -m shrdlu.env.cli.render_main --scenario first-version --out scene.svg
    python3 -m shrdlu.env.cli.render_main --seed 3 --out scene.png
    python3 -m shrdlu.env.cli.render_main --seed 3 --stage both --out-dir pictures
    python3 -m shrdlu.env.cli.render_main --check --seed 3

The picture is the only thing a vision testee is shown, so it carries every
object's id, colour, size, shape and position.  ``--check`` proves it: it reads
the drawing back from its own geometry and compares against the truth.

The format follows the ``--out`` extension: ``.png`` rasterises, anything else
stays SVG.  ``--out-dir`` (one picture per state) writes SVG.  SVG needs nothing
installed; PNG needs Pillow and is what most vision models actually want.
"""

from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from typing import List, Tuple

from ... import settings, snapshot
from .. import authoring, render, scenario, worldgen


def build_parser(cfg: "settings.Settings" = None) -> argparse.ArgumentParser:
    cfg = cfg or settings.load("render")
    parser = argparse.ArgumentParser(
        prog="shrdlu-render",
        description="Draw a scene (or an exam's states) as SVG. "
                    "Defaults come from %s." % settings.CONFIG_NAME,
    )
    parser.add_argument("--scenario", default=cfg["scenario"],
                        help="scenario name or path to draw")
    parser.add_argument("--seed", type=int, default=0,
                        help="generate a scene+exam from this seed when --scenario is absent")
    parser.add_argument("--stage", default=cfg["stage"],
                        choices=("initial", "final", "both"),
                        help="which state to draw")
    parser.add_argument("--labels", action=argparse.BooleanOptionalAction,
                        default=cfg["labels"],
                        help="draw the id plates (--no-labels is a harder condition)")
    parser.add_argument("--out", default=None,
                        help="write a single picture to this path")
    parser.add_argument("--out-dir", default=cfg["out_dir"],
                        help="write one picture per state into this directory")
    parser.add_argument("--check", action="store_true",
                        help="do not write; read the drawing back and compare with the truth")
    parser.add_argument("--quiet", action=argparse.BooleanOptionalAction,
                        default=cfg["quiet"],
                        help="print only the one-line result")
    parser.set_defaults(cfg=cfg)          # the standing values, from shrdlu.ini
    return parser


def states(args) -> List[Tuple[str, str, object]]:
    """``(label, output stem, world)`` for each state requested."""
    if args.scenario:
        loaded = scenario.load(args.scenario)
        name = loaded.name
    else:
        scene = worldgen.generate(worldgen.Spec(), seed=args.seed)
        loaded, _ = authoring.author(scene.state, scene.name, seed=args.seed)
        name = loaded.name

    out: List[Tuple[str, str, object]] = []
    if args.stage in ("initial", "both"):
        out.append(("initial", "%s-initial" % name, loaded.world()))
    if args.stage in ("final", "both"):
        out.append(("final", "%s-final" % name, loaded.final_world()))
    return out


def check(world, labels: bool) -> List[str]:
    """Everything wrong with the drawing; empty means it carries the state."""
    problems: List[str] = []
    drawing = render.plan(world, labels=labels)
    if not drawing.shapes:
        problems.append("nothing was drawn")
        return problems

    svg = render.render_svg(drawing, labels=labels)
    try:
        ET.fromstring(svg)
    except ET.ParseError as exc:
        problems.append("the SVG is not well-formed XML: %s" % exc)
        return problems

    back = render.read_back(drawing)
    want = render.relation_key(snapshot.to_snapshot(world))
    got = render.relation_key(back)
    for ident, expected in want.items():
        if ident not in got:
            problems.append("%s is in the world but not in the picture" % ident)
        elif got[ident] != expected:
            problems.append("%s: truth %s but the picture says %s"
                            % (ident, expected, got[ident]))

    if labels:
        drawn = [s.ident for s in drawing.shapes]
        if len(set(drawn)) != len(drawn):
            problems.append("two objects share a label")

    # carrying the state and being legible are separate claims, and only the
    # first is fatal
    problems.extend(render.audit(drawing, labels=labels))
    return problems


def warnings_for(world, labels: bool) -> List[str]:
    return render.size_warnings(render.plan(world, labels=labels))


def output_format(args) -> str:
    """``"png"`` when the requested output is a PNG, else ``"svg"``.

    A single picture says what it is by its own extension; batch output
    (``--out-dir``) stays SVG, which needs nothing installed.
    """
    if args.out and args.out.lower().endswith(".png"):
        return "png"
    return "svg"


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except settings.SettingsError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    labels = args.labels
    exit_code = 0
    targets = states(args)
    fmt = output_format(args)

    for stage, stem, world in targets:
        if args.check:
            problems = check(world, labels)
            if problems:
                print("%s: NOT COMPLETE" % stem)
                for problem in problems:
                    print("  - %s" % problem)
                exit_code = 1
            else:
                print("%s: ok (%d objects, the picture carries the whole state)"
                      % (stem, len(world.actual_objects())))
                for note in warnings_for(world, labels):
                    print("    (注意) %s" % note)
            continue

        target = None
        if args.out and len(targets) == 1:
            target = args.out
        elif args.out_dir:
            target = os.path.join(args.out_dir, "%s.%s" % (stem, fmt))
        if target is None:
            # no destination: print the SVG itself
            print(render.to_svg(world, labels=labels))
            continue

        try:
            if fmt == "png":
                render.to_png(world, target, labels=labels, scale=args.cfg["scale"])
            else:
                render.save(world, target, labels=labels)
        except render.RenderError as exc:
            print("error: %s" % exc, file=sys.stderr)
            return 2

        if not args.quiet:
            drawing = render.plan(world, labels=labels)
            print("%s (%s): %d objects -> %s"
                  % (stem, stage, len(drawing.shapes), target))
            print("    查看：open %s   （或拖进浏览器 / 预览）" % target)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
