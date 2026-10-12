"""``shrdlu-play`` — watch a match go by, one exchange at a time.

    python3 -m shrdlu.env.cli.play_main --seed 3
    python3 -m shrdlu.env.cli.play_main --scenario first-version

After every exchange it pauses and shows

* what the env sent and what the testee did with it;
* the **true** state, as the env knows it;
* the **second** state — what the testee's own calls did to the world — with the
  disagreements marked, because that disagreement *is* the measurement.

That comparison is the env's own, so it needs nothing from the testee's private
account of the world.  A built-in implementation is run **in this process**;
a literal command line is launched as a subprocess, in which case there is no
prompt history to show but the pause works all the same.

At the pause you can just carry on, or interfere:

| 输入 | 作用 |
| --- | --- |
| 直接回车 / 空格 | 继续下一步 |
| `q <英文问句>` | 额外问 testee 一句（不记入正式记录、不影响判定） |
| `c <英文指令>` | 额外下一条指令（**会真的改变世界**，影响后续判定） |
| `s` | 重新显示当前两个状态 |
| `v` | 显示 testee 至今的历史 |
| `h` | 帮助 |
| `x` | 就此打住 |

For a match with no pause and no interference, use ``shrdlu-env``.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import List, Optional, TextIO

from ... import questions, settings, transport
from ...testee import nlp
from .. import authoring, host, impls, scenario
from ...world import World

HELP = """\
  回车 / 空格   继续下一步
  q <问句>      额外问一句（如 q Is the red cube clear?）
  c <指令>      额外下一条（如 c Put the green cube on the red cube.）
  s             重新显示状态
  v             显示 testee 的历史
  h             显示本帮助
  x             结束测试
"""


# --------------------------------------------------------------------------
# Console
# --------------------------------------------------------------------------


class Console:
    """Reading from the terminal.  Swappable so the viewer can be tested."""

    def __init__(self, stream: TextIO = None) -> None:
        self.stream = stream if stream is not None else sys.stdin

    def read_command(self) -> str:
        try:
            return input("> ").strip()
        except EOFError:
            return "x"


class ScriptedConsole(Console):
    """Feeds pre-recorded commands; used by the tests."""

    def __init__(self, lines: List[str]) -> None:
        super().__init__(stream=None)
        self.lines = list(lines)
        self.prompts = 0

    def read_command(self) -> str:
        self.prompts += 1
        if not self.lines:
            return "x"
        return self.lines.pop(0).strip()


# --------------------------------------------------------------------------
# Showing state
# --------------------------------------------------------------------------


def position_of(world: World, ident: str) -> str:
    obj = world.get(ident)
    if obj is None:
        return "(不存在)"
    pos = world.pos_of(obj)
    if pos[0] == "table":
        return "on the table"
    if pos[0] == "hand":
        return "in hand"
    if pos[0] == "in":
        return "in %s" % pos[1]
    return "on %s" % pos[1]


def state_table(truth: World, model: Optional[World]) -> List[str]:
    """A per-object comparison of the world now and what the testee shows."""
    lines: List[str] = []
    header = "  %-14s %-16s %-8s %-8s %s" % (
        "id", "是什么", "世界的当前状态", "", "被测者表现出的状态")
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    ids: List[str] = [o.ident for o in truth.actual_objects()]
    if model is not None:
        for obj in model.actual_objects():
            if obj.ident not in ids:
                ids.append(obj.ident)

    for ident in ids:
        true_obj = truth.get(ident)
        believed = model.get(ident) if model is not None else None
        describe = true_obj or believed
        true_pos = position_of(truth, ident)
        if model is None:
            belief = "?"
            mark = ""
        elif believed is None:
            belief = "(不存在)"
            mark = "  <<<"
        else:
            belief = position_of(model, ident)
            mark = "" if belief == true_pos else "  <<< 不一致"
        lines.append("  %-14s %-16s %-16s %-8s %s%s" % (
            ident,
            "%s %s %s" % (describe.size, describe.color, describe.kind) if describe else "?",
            true_pos, "", belief, mark,
        ))
    if model is None:
        lines.append("")
        lines.append("  (看不到被测者的状态：它不在这进程里)")
    return lines


def truth_summary(truth: World) -> List[str]:
    """A compact table of the true state."""
    lines = []
    for obj in truth.actual_objects():
        lines.append("  %-14s %s %s %-8s %s" % (
            obj.ident, obj.size, obj.color, obj.kind, position_of(truth, obj.ident)))
    return lines


# --------------------------------------------------------------------------
# Viewer
# --------------------------------------------------------------------------


@dataclass
class Viewer:
    """Pauses after every exchange and lets the operator look or interfere."""

    console: Console
    out: TextIO = sys.stdout
    scenario: Optional[scenario.Scenario] = None
    ask_before_observe: bool = True
    probes: List[host.Step] = field(default_factory=list)

    # -- helpers -----------------------------------------------------------
    def say(self, text: str = "") -> None:
        print(text, file=self.out)

    def show(self, truth: World, second: Optional[World] = None,
             testee_obj=None) -> None:
        """Show the truth beside the second state, when there is one.

        Inside a match that second state is the one the env derives from the
        testee's calls — the same comparison the second stage is judged on.
        Outside one (an ad-hoc probe) there is nothing to compare with but the
        in-process testee's own model, and for a testee in another process
        there is nothing at all: the env never reads its private account.
        """
        other = second if second is not None else getattr(testee_obj, "model", None)
        if other is None:
            # nothing to compare against: just report what is true
            self.say("  ── 世界的当前状态（测试者知道的）" + "─" * 40)
            for line in truth_summary(truth):
                self.say(line)
            self.say("")
            self.say("  (看不到第二份状态：只有测试内才有)")
            return
        label = "被测者通过操作表现出的世界状态" if second is not None else "被测者私有模型"
        self.say("  ── 世界的当前状态与 %s（不一致处标 <<<）" % label + "─" * 12)
        for line in state_table(truth, other):
            self.say(line)

    # -- the callback ------------------------------------------------------
    def __call__(self, event: host.StepEvent) -> None:
        self.say("")
        if event.phase == "observe":
            self.say("═══ 测试开始：测试者把初始场景给了被测者（只有这一次）")
        else:
            step = event.step
            mark = "ok  " if step.ok else "FAIL"
            what = "指令" if event.phase == "instruction" else "问句"
            stage = host.STAGE_SHORT.get(event.stage, "")
            self.say("═══ 第 %d 步 · %s%s" % (
                event.index, ("%s · " % stage) if stage else "", what))
            self.say("  测试者  →  %s" % step.sent)
            self.say("  ←  %s  %s%s" % (mark, step.received,
                                        "" if step.ok else "   (%s)" % step.note))
            if step.truth_expected:
                self.say("     世界的当前状态的答案是 %s（这一份%s）" % (
                    step.truth_expected, "答对" if step.matches_truth else "答错"))
            if step.drift:
                self.say("     ⚠ 两份状态不一致：%s" % step.drift)
        self.show(event.truth, event.second, event.testee)
        self.prompt(event)

    def prompt(self, event: host.StepEvent) -> None:
        while True:
            self.say("")
            self.say("  [回车继续 · h 帮助]")
            command = self.console.read_command()
            if command == "":
                return
            if command in ("h", "H", "?"):
                self.say(HELP)
                continue
            if command in ("x", "X", "q!", "quit", "exit"):
                raise KeyboardInterrupt
            if command in ("s", "S"):
                self.show(event.truth, event.second, event.testee)
                continue
            if command in ("v", "V"):
                self.show_history(event.testee)
                continue
            if command[:1] in ("q", "Q"):
                self.probe_question(event, command[1:].strip())
                continue
            if command[:1] in ("c", "C"):
                self.probe_command(event, command[1:].strip())
                continue
            self.say("  看不懂 %r；h 看帮助" % command)

    # -- interference ------------------------------------------------------
    def probe_question(self, event: host.StepEvent, text: str) -> None:
        if not text:
            self.say("  用法： q Is the red cube clear?")
            return
        try:
            question = nlp.parse_question(text)
        except nlp.ParseError as exc:
            self.say("  这不是我能问的问句：%s" % exc)
            return
        invalid = questions.validate(question, event.truth)
        if invalid:
            self.say("  这道题对当前状态问不了：%s" % invalid)
            return
        step = host.ask_question(event.truth, event.testee, event.result, question, text)
        self.probes.append(step)
        self.say("  (临时提问，不进正式记录)  %s  %s" % (
            "答对" if step.ok else "答错", step.received))
        if not step.ok:
            self.say("    正确答案是 %s" % step.expected)

    def probe_command(self, event: host.StepEvent, text: str) -> None:
        if not text:
            self.say("  用法： c Put the green cube on the red cube.")
            return
        try:
            op, descs = nlp.parse_command(text)
        except nlp.ParseError as exc:
            self.say("  这不是我能下的指令：%s" % exc)
            return
        try:
            args = [questions.unique(event.truth, d).ident for d in descs]
        except questions.ResolutionError as exc:
            self.say("  在世界的当前状态里指不到唯一对象：%s" % exc)
            return
        step = host.issue_instruction(event.truth, event.testee, event.result,
                                      op, args, text, second=event.second)
        self.probes.append(step)
        self.say("  (临时指令，会真的改变世界)  %s  %s" % (
            "通过" if step.ok else "不通过", step.received))
        self.say("")
        self.show(event.truth, event.second, event.testee)

    def show_history(self, testee_obj) -> None:
        history = getattr(testee_obj, "history", None)
        if not history:
            self.say("  (没有历史)")
            return
        for entry in history:
            self.say("  %-9s %-46s %s" % (entry.kind, entry.text[:46], entry.outcome))


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def build_parser(cfg: "settings.Settings" = None) -> argparse.ArgumentParser:
    cfg = cfg or settings.load("play")
    parser = argparse.ArgumentParser(
        prog="shrdlu-play",
        description="Play a match step by step, watching both sides. "
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
    parser.add_argument("--pause", action=argparse.BooleanOptionalAction,
                        default=cfg["pause"],
                        help="stop after every exchange (use --no-pause to run straight through)")
    return parser


def main(argv=None, console: Optional[Console] = None, out: TextIO = None) -> int:
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

    console = console if console is not None else Console()
    out = out if out is not None else sys.stdout
    viewer = Viewer(console=console, out=out)

    def say(text: str = "") -> None:
        print(text, file=out)

    def show_probes() -> None:
        if not viewer.probes:
            return
        say("")
        say("临时试探 %d 次：" % len(viewer.probes))
        for step in viewer.probes:
            say("  " + step.render())

    say("场景 %s：%d 条指令，%d 道题" % (
        loaded.name, len(loaded.instructions), len(loaded.questions)))
    say("（任意时刻输入 h 查看能做什么）")

    result = None
    code = 1
    try:
        if args.pause:
            result = host.run(loaded, player, on_step=viewer,
                              observe=args.observe)
        else:
            result = host.run(loaded, player, observe=args.observe)
    except host.HostError as exc:
        print("error: %s" % exc, file=sys.stderr)
        code = 2
    except (KeyboardInterrupt, EOFError):
        say("")
        say("（中途结束）")
        # the probes made before quitting are still worth reporting
        show_probes()
        code = 130
    finally:
        stderr = close()

    if result is not None:
        say("")
        say(result.render())
        show_probes()
        code = 0 if result.understood else 1
    if stderr and stderr.strip():
        print("被测者的 stderr：\n%s" % stderr.strip(), file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
