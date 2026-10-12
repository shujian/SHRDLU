"""``shrdlu-env`` — the env as a standalone program.

Loads (or generates) an exam, launches the testee as a separate process, plays
one match and prints the record.

    python3 -m shrdlu.env.cli.env_main --scenario first-version
    python3 -m shrdlu.env.cli.env_main --seed 3 --record run.json
    python3 -m shrdlu.env.cli.env_main --questions 15 --seed 13
    python3 -m shrdlu.env.cli.env_main --testee frozen              # by name
    python3 -m shrdlu.env.cli.env_main --testee "python3 my_testee.py"

A ``--testee`` value that names a built-in implementation is launched with the
interpreter running the env, so a bare run works from a checkout without
installing anything; anything else is run as the command given.
"""

from __future__ import annotations

import argparse
import json
import sys

from ... import settings, transport
from .. import authoring, generator, host, impls, scenario

DEFAULT_TIMEOUT = 10.0


def build_parser(cfg: "settings.Settings" = None) -> argparse.ArgumentParser:
    cfg = cfg or settings.load("env")
    parser = argparse.ArgumentParser(
        prog="shrdlu-env",
        description="Host one match between an env and a testee, and judge it. "
                    "Defaults come from %s." % settings.CONFIG_NAME,
    )
    parser.add_argument("--scenario", default=cfg["scenario"],
                        help="scenario name (from shrdlu/scenarios/) or a path to a .json file")
    parser.add_argument("--questions", type=int, default=cfg["questions"],
                        help="generate this many questions instead of using the scenario's bank")
    parser.add_argument("--seed", type=int, default=cfg["seed"],
                        help="seed: with --questions it fixes the generated bank; on its own "
                             "it makes a whole exam on the spot")
    parser.add_argument("--testee", default=cfg["testee"],
                        help="a built-in name, a module:Class, or a command that runs the testee")
    parser.add_argument("--observe", default=cfg["observe"], choices=("state", "image"),
                        help="what the opening message carries: the state or a picture")
    parser.add_argument("--record", default=cfg["record"],
                        help="write the match record as JSON to this path")
    parser.add_argument("--quiet", action=argparse.BooleanOptionalAction,
                        default=cfg["quiet"],
                        help="print only the summary, not the whole record")
    parser.set_defaults(cfg=cfg)          # the standing values, from shrdlu.ini
    return parser


def default_testee_command(impl: str) -> list:
    """The command line for a built-in implementation (kept for callers of old)."""
    return impls.command_line(impl)


def load_bank(args) -> scenario.Scenario:
    shapes = tuple(s.strip() for s in args.cfg["shapes"].split(",") if s.strip())
    return authoring.load_exam(args.scenario, seed=args.seed,
                               questions_count=args.questions, shapes=shapes)


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except settings.SettingsError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    try:
        loaded = load_bank(args)
    except scenario.ScenarioError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    try:
        player = transport.SubprocessTestee(
            impls.command_line(args.testee), timeout=args.cfg["timeout"],
            cwd=impls.PROJECT_ROOT)
    except transport.TransportError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    try:
        result = host.run(loaded, player, observe=args.observe)
    except host.HostError as exc:
        print("error: %s" % exc, file=sys.stderr)
        player.close()
        return 2
    finally:
        stderr = player.close()

    if not args.quiet:
        print(result.render())
    print()
    print(result.summary())
    if args.record:
        with open(args.record, "w", encoding="utf-8") as handle:
            json.dump(result.to_json(), handle, ensure_ascii=False, indent=2)
        print("record written to %s" % args.record)
    if stderr and stderr.strip():
        print("被测者的 stderr：\n%s" % stderr.strip(), file=sys.stderr)

    return 0 if result.understood else 1


if __name__ == "__main__":
    raise SystemExit(main())
