"""``shrdlu-report`` — play a match and write it out as one HTML page.

    python3 -m shrdlu.env.cli.report_main --scenario first-version --out report.html
    python3 -m shrdlu.env.cli.report_main --seed 7 --testee frozen --out r.html
    python3 -m shrdlu.env.cli.report_main --questions 12 --seed 3 --out r.html

The page is self-contained: scenes are inline SVG, navigation is plain
``<details>``, and there is no JavaScript at all.  Open it with

    open report.html

A built-in testee is run **in this process**; a literal command line is
launched as a subprocess.  Either way the page compares the truth with the
**second** state the env derives from the testee's calls — the same comparison
the second stage is judged on.  The testee's private model is never read.
"""

from __future__ import annotations

import argparse
import sys

from ... import settings, transport
from .. import authoring, host, impls, scenario, webreport


def build_parser(cfg: "settings.Settings" = None) -> argparse.ArgumentParser:
    cfg = cfg or settings.load("report")
    parser = argparse.ArgumentParser(
        prog="shrdlu-report",
        description="Play one match and write a self-contained HTML report. "
                    "Defaults come from %s." % settings.CONFIG_NAME,
    )
    parser.add_argument("--scenario", default=cfg["scenario"],
                        help="scenario name or path")
    parser.add_argument("--questions", type=int, default=cfg["questions"],
                        help="generate this many questions instead of using the bank")
    parser.add_argument("--seed", type=int, default=cfg["seed"],
                        help="seed: with --questions it fixes the generated bank; on its own "
                             "it makes a whole scene+exam on the spot")
    parser.add_argument("--observe", default=cfg["observe"],
                        choices=("state", "image"),
                        help="what the opening message carries: state or image")
    parser.add_argument("--testee", default=cfg["testee"],
                        help="a built-in name, a module:Class, or a command that runs the testee")
    parser.add_argument("--out", default=cfg["out"],
                        help="where to write the report")
    parser.add_argument("--open", dest="open_when_done",
                        action=argparse.BooleanOptionalAction,
                        default=cfg["open"],
                        help="open the report in a browser when it is written")
    parser.add_argument("--quiet", action=argparse.BooleanOptionalAction,
                        default=cfg["quiet"],
                        help="print only the one-line summary")
    return parser


def build_testee(name: str, model: str = None, url: str = None):
    """The in-process testee for a built-in implementation name."""
    try:
        return impls.build(name, model=model, url=url)
    except LookupError as exc:
        raise SystemExit(str(exc))


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except settings.SettingsError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    try:
        loaded = authoring.load_exam(args.scenario, seed=args.seed,
                                     questions_count=args.questions)
    except scenario.ScenarioError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    try:
        player, close = impls.as_testee(args.testee,
                                        getattr(args, 'model', None),
                                        getattr(args, 'ollama_url', None))
    except transport.TransportError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    recorder = webreport.Recorder(testee_label=args.testee)
    code = 1
    stderr = None
    try:
        result = host.run(loaded, player, on_step=recorder,
                          observe=args.observe)
    except host.HostError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    finally:
        stderr = close()

    page = webreport.build(result, recorder, scenario_=loaded)
    webreport.save(page, args.out)

    if args.quiet:
        print("%s: verdict=%s, %d/%d" % (loaded.name, result.verdict,
                                         result.correct, len(result.asked)))
    else:
        print("场景 %s · 被测者 %s" % (loaded.name, args.testee))
        print("  %s" % result.summary())
        print("  画面 %d 张（去重后）" % len(recorder.pictures))
        print("  报告 %.0f KB -> %s" % (len(page) / 1024.0, args.out))
        print("  查看：open %s" % args.out)

    if stderr and stderr.strip():
        print("被测者的 stderr：\n%s" % stderr.strip(), file=sys.stderr)

    if args.open_when_done:
        import webbrowser
        webbrowser.open("file://" + __import__("os").path.abspath(args.out))
    return 0 if result.understood else 1


if __name__ == "__main__":
    raise SystemExit(main())
