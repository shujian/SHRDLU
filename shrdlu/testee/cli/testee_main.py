"""``shrdlu-testee`` — the testee as a standalone program.

Reads protocol messages on stdin, writes replies on stdout, one JSON object per
line.  It never sees the world's true state: only the single ``observe`` message
it is sent at the start.

    python3 -m shrdlu.testee.cli.testee_main --impl example

``--impl`` 选一个内置实现（只有 ``example``），或用自己的 ``模块:类``。
"""

from __future__ import annotations

import argparse
import sys

from ... import settings, transport
from .. import registry


def build_implementation(name: str, model: str = None, url: str = None):
    """The testee implementation selected by name."""
    try:
        return registry.build(name, model=model, url=url)
    except LookupError as exc:
        raise SystemExit(str(exc))


def build_parser(cfg: "settings.Settings" = None) -> argparse.ArgumentParser:
    cfg = cfg or settings.load("testee")
    parser = argparse.ArgumentParser(
        prog="shrdlu-testee",
        description="Answer protocol messages on stdin, from a private model of the world. "
                    "Defaults come from %s." % settings.CONFIG_NAME,
    )
    parser.add_argument(
        "--impl",
        default=cfg["impl"],
        help="which implementation to run: example (default), or a module:Class",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list the available implementations and exit",
    )
    parser.set_defaults(cfg=cfg)          # the standing values, from shrdlu.ini
    return parser


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except settings.SettingsError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    if args.list:
        for name in registry.names():
            print("%s\t%s" % (name, registry.describe(name)))
        return 0

    implementation = build_implementation(args.impl)
    return transport.serve(
        implementation,
        on_error=lambda exc: print("testee error: %s" % exc, file=sys.stderr),
    )


if __name__ == "__main__":
    raise SystemExit(main())
