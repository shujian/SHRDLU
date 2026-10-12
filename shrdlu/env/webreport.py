"""A self-contained HTML report of one match.

This is a **read-only view**.  It reads a finished match and lays it out for a
person; it does not judge, does not talk to a testee, and is not part of the
protocol.  Keeping that boundary is what stops a viewer from quietly becoming
part of the thing being measured.

The page needs no server, no network and no JavaScript: the scenes are inline
SVG (which is text), navigation is plain ``<details>``, and everything else is
escaped text.  One file, opens anywhere, and the same match always produces the
same bytes.

Two things it deliberately makes visible:

* **the truth beside the state the testee's own calls produced**, with the
  disagreements marked — that gap is what the operations stage is judged on;
* **which questions required reasoning** and which could be answered from the
  single observation the testee was given.

It shows the three stages of the match (README.md §4.2) as three groups of steps,
each with its own conclusion, and it reads the two states the *env* maintains:
the testee's private account of the world is never read, here or anywhere else.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .. import snapshot
from . import render
from .host import MatchResult, STAGES, STAGE_LABELS, STAGE_SHORT, Step, StepEvent
from .scenario import Scenario

#: Text that would mean we had built a page that executes something.
_FORBIDDEN = ("<script", "<iframe", "<object", "<embed", "javascript:")

#: The comparison itself lives with the states, so the report and the judgement
#: can never disagree about what "these two states differ" means.
differences = snapshot.differences

#: What the second picture in a comparison is, when it is the state the env
#: derived from the testee's calls rather than a private model it can see.
SECOND_STATE_LABEL = "被测者通过操作表现出的世界状态"
PRIVATE_MODEL_LABEL = "被测者私有模型"


class ReportError(Exception):
    """Raised when a report cannot be built."""


@dataclass
class Frame:
    """One exchange, with the pictures that go with it."""

    index: int
    phase: str
    step: Optional[Step]
    truth_svg: int          # index into the picture pool
    model_svg: int          # -1 when no second state is available
    mismatches: List[Tuple[str, str, str]] = field(default_factory=list)
    stage: str = ""         # "initial" | "operations" | "final"
    belief_label: str = PRIVATE_MODEL_LABEL


class Recorder:
    """Collects a frame per exchange.  Pass it to :func:`shrdlu.host.run`."""

    def __init__(self, testee_label: str = "") -> None:
        self.testee_label = testee_label
        self.frames: List[Frame] = []
        self._pool: Dict[str, int] = {}
        self._pictures: List[str] = []

    def __call__(self, event: StepEvent) -> None:
        # The state the env derived from the testee's calls, when there is one;
        # a private model only for exchanges outside a match (the viewer's
        # ad-hoc probes), where no second state exists.
        second = event.second
        label = SECOND_STATE_LABEL
        if second is None:
            second = getattr(event.testee, "model", None)
            label = PRIVATE_MODEL_LABEL
        model_svg = -1
        if second is not None:
            model_svg = self._intern(render.to_svg(second))
        self.frames.append(Frame(
            index=event.index,
            phase=event.phase,
            step=event.step,
            truth_svg=self._intern(render.to_svg(event.truth)),
            model_svg=model_svg,
            mismatches=snapshot.differences(event.truth, second),
            stage=event.stage,
            belief_label=label,
        ))

    def _intern(self, svg: str) -> int:
        """Reuse a picture when the same scene has already been drawn."""
        key = svg
        if key not in self._pool:
            self._pool[key] = len(self._pictures)
            self._pictures.append(svg)
        return self._pool[key]

    @property
    def pictures(self) -> Sequence[str]:
        return self._pictures


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

STYLE = """
:root { --ink:#1c1c1c; --dim:#6b6b6b; --line:#dcdcdc; --ok:#1d7a3f; --bad:#b3261e;
        --okbg:#e8f5ec; --badbg:#fdecea; --reason:#7a4bd0; --recall:#6b6b6b; }
* { box-sizing: border-box; }
body { margin:0; padding:32px 24px 64px; background:#fafafa; color:var(--ink);
       font:15px/1.65 -apple-system, "Helvetica Neue", "PingFang SC", sans-serif; }
main { max-width: 980px; margin: 0 auto; }
h1 { font-size:22px; margin:0 0 4px; }
h2 { font-size:17px; margin:36px 0 12px; padding-bottom:6px; border-bottom:2px solid var(--line); }
.sub { color:var(--dim); margin:0 0 18px; }
.verdict { display:inline-block; padding:3px 12px; border-radius:999px; font-weight:700; font-size:13px; }
.verdict.ok { background:var(--okbg); color:var(--ok); }
.verdict.bad { background:var(--badbg); color:var(--bad); }
ul.facts { list-style:none; padding:0; margin:14px 0 0; display:flex; flex-wrap:wrap; gap:8px 20px; }
ul.facts li { color:var(--dim); font-size:13px; }
ul.facts b { color:var(--ink); font-weight:600; }
ol.timeline { list-style:none; padding:0; margin:0; }
li.step { border:1px solid var(--line); border-left:4px solid var(--line); border-radius:8px;
          background:#fff; padding:12px 16px; margin:0 0 10px; }
li.step.ok { border-left-color:var(--ok); }
li.step.bad { border-left-color:var(--bad); }
.head { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }
.badge { font-size:11px; font-weight:700; letter-spacing:.04em; text-transform:uppercase;
         color:var(--dim); background:#f0f0f0; border-radius:4px; padding:2px 7px; }
.badge.ok { background:var(--okbg); color:var(--ok); }
.badge.bad { background:var(--badbg); color:var(--bad); }
.badge.reason { background:#f1e9ff; color:var(--reason); }
.badge.recall { background:#f0f0f0; color:var(--recall); }
code, pre { font-family: ui-monospace, Menlo, monospace; font-size:13px; }
.sent { font-weight:600; }
.reply { color:var(--dim); font-size:13px; margin-top:2px; }
.note { color:var(--bad); font-size:13px; }
details { margin-top:10px; }
summary { cursor:pointer; color:var(--dim); font-size:13px; }
.pair { display:flex; gap:20px; flex-wrap:wrap; margin-top:10px; }
.pair figure { margin:0; }
.pair svg { max-width:460px; height:auto; border:1px solid var(--line); border-radius:6px; background:#fff; }
.pair figcaption { font-size:12px; color:var(--dim); margin-bottom:4px; }
table { border-collapse:collapse; width:100%; margin-top:10px; font-size:13px; }
th, td { text-align:left; padding:5px 10px; border-bottom:1px solid var(--line); }
th { color:var(--dim); font-weight:600; }
td.bad { color:var(--bad); font-weight:600; }
pre.record { background:#fff; border:1px solid var(--line); border-radius:6px; padding:14px;
             overflow:auto; max-height:460px; }
footer { color:var(--dim); font-size:12px; margin-top:40px; }
"""


def esc(text: object) -> str:
    return html.escape("" if text is None else str(text))


def build(
    result: MatchResult,
    recorder: Recorder,
    scenario_: Optional[Scenario] = None,
    title: Optional[str] = None,
) -> str:
    """The whole report as one HTML document."""
    for svg in recorder.pictures:
        lowered = svg.lower()
        for bad in _FORBIDDEN:
            if bad in lowered:
                raise ReportError("refusing to embed a picture containing %r" % bad)

    name = result.scenario
    marks = _reasoning_marks(scenario_)

    body: List[str] = []
    body.append("<main>")
    body.append(_header(result, recorder, scenario_, title))

    initial = recorder.frames[0] if recorder.frames else None
    if initial is not None:
        body.append("<h2>初始场景</h2>")
        body.append("<div class='pair'><figure><figcaption>测试者给了被测者这一次观察"
                    "（此后没有别的消息）</figcaption>%s</figure></div>"
                    % recorder.pictures[initial.truth_svg])

    body.append("<h2>测试</h2>")
    body.append("<ol class='timeline'>")
    for frame in recorder.frames[1:]:
        body.append(_step(frame, recorder, marks))
    body.append("</ol>")

    body.append(_summary(result, recorder))
    body.append("<h2>完整记录</h2>")
    body.append("<details><summary>展开 JSON（这份报告就是用它生成的）</summary>"
                "<pre class='record'>%s</pre></details>"
                % esc(json.dumps(result.to_json(), ensure_ascii=False, indent=2)))
    body.append("<footer>由 shrdlu-report 生成 · 仅从测试记录重放，不参与判分</footer>")
    body.append("</main>")

    return (
        "<!DOCTYPE html>\n<html lang='zh'>\n<head>\n<meta charset='utf-8'>\n"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>\n"
        "<title>%s</title>\n<style>%s</style>\n</head>\n<body>\n%s\n</body>\n</html>\n"
        % (esc(title or "测试报告 · %s" % name), STYLE, "\n".join(body))
    )


def _header(result: MatchResult, recorder: Recorder, scenario_,
            title: Optional[str]) -> str:
    facts: List[str] = []
    if scenario_ is not None and scenario_.generated:
        seed = scenario_.generated.get("seed")
        if seed is not None:
            facts.append("种子 <b>%s</b>" % esc(seed))
    facts.append("指令 <b>%d</b>" % len([f for f in recorder.frames
                                         if f.phase == "instruction"]))
    for name in STAGES:
        if name in result.stages:
            stage = result.stages[name]
            facts.append("%s <b>%d/%d</b>" % (
                STAGE_SHORT[name], stage.correct, stage.total))
    facts.append("问句合计 <b>%d</b>" % len(result.asked))
    facts.append("不重复的画面 <b>%d 张</b>" % len(recorder.pictures))
    if recorder.testee_label:
        facts.append("被测者 <b>%s</b>" % esc(recorder.testee_label))
    if result.illegal_attempt:
        facts.append("非法操作 <b>%s</b>" % esc(result.illegal_attempt))

    verdict_class = "ok" if result.understood else "bad"
    verdict_text = "理解" if result.understood else "不理解"
    return (
        "<h1>%s</h1>\n<p class='sub'>判定 <span class='verdict %s'>%s</span></p>\n"
        "<ul class='facts'>%s</ul>"
        % (esc(title or result.scenario), verdict_class, verdict_text,
           "".join("<li>%s</li>" % f for f in facts))
    )


def _reasoning_marks(scenario_: Optional[Scenario]) -> Dict[str, bool]:
    """Which questions needed the instructions to have been understood.

    "recall" ones can be answered straight from the single observation the
    testee was given, so they say less about understanding than they look.
    """
    if scenario_ is None or not scenario_.questions:
        return {}
    from .authoring import is_discriminating

    initial, final = scenario_.world(), scenario_.final_world()
    return {
        text: is_discriminating(question, initial, final)
        for question, text in zip(scenario_.questions, scenario_.question_text)
    }


def _step(frame: Frame, recorder: Recorder, marks: Dict[str, bool]) -> str:
    step = frame.step
    if step is None:
        return ""
    label = "指令" if frame.phase == "instruction" else "问句"
    if frame.stage:
        label = "%s · %s" % (STAGE_SHORT.get(frame.stage, frame.stage), label)
    css = "ok" if step.ok else "bad"
    badge = "通过" if step.ok else "不通过"

    parts = ["<li class='step %s'>" % css,
             "<div class='head'><span class='badge'>%s %d</span>"
             "<span class='sent'>%s</span>"
             "<span class='badge %s'>%s</span></div>"
             % (esc(label), frame.index, esc(step.sent), css, badge)]
    parts.append("<div class='reply'>← %s</div>" % esc(step.received))
    if not step.ok and step.note:
        parts.append("<div class='note'>%s</div>" % esc(step.note))
    if frame.phase == "question":
        parts.append("<div class='reply'>期望 <code>%s</code></div>" % esc(step.expected))
        if step.truth_expected:
            # only possible in the third stage: its baseline is the state the
            # testee's calls produced, which is not always the true one
            parts.append(
                "<div class='note'>世界的当前状态的答案是 <code>%s</code>（按它的调用%s）</div>"
                % (esc(step.truth_expected), "答对了" if step.matches_truth else "答错了"))
        # Only the third stage needs reasoning: the first one is answered
        # straight from the observation the testee was given.
        mark = marks.get(step.sent) if frame.stage == "final" else None
        if mark is True:
            parts.append("<span class='badge reason' title='答案在指令前后会变，"
                         "必须推演才能答对'>必须推演</span>")
        elif mark is False:
            parts.append("<span class='badge recall' title='答案在指令前后相同，"
                         "回放初始观察即可答对'>回放即可</span>")

    if frame.phase == "instruction":
        if step.drift:
            parts.append("<div class='note'>两份状态不一致：%s</div>" % esc(step.drift))
        parts.append(_pictures(frame, recorder))

    parts.append("</li>")
    return "".join(parts)


def _pictures(frame: Frame, recorder: Recorder) -> str:
    truth = recorder.pictures[frame.truth_svg]
    if frame.model_svg < 0:
        return ("<details><summary>这一步之后的状态</summary>"
                "<div class='pair'><figure><figcaption>世界的当前状态</figcaption>%s</figure></div>"
                "</details>" % truth)

    belief = recorder.pictures[frame.model_svg]
    table = ""
    if frame.mismatches:
        rows = "".join(
            "<tr><td>%s</td><td>%s</td><td class='bad'>%s</td></tr>" % (
                esc(ident), esc(mine), esc(theirs))
            for ident, mine, theirs in frame.mismatches
        )
        table = ("<table><tr><th>id</th><th>世界的当前状态</th><th>%s</th></tr>%s</table>"
                 % (esc(frame.belief_label), rows))
        caption = "这一步之后 · <b>%d 处不一致</b>" % len(frame.mismatches)
    else:
        caption = "这一步之后 · 完全一致"
    return ("<details><summary>%s</summary><div class='pair'>"
            "<figure><figcaption>世界的当前状态</figcaption>%s</figure>"
            "<figure><figcaption>%s</figcaption>%s</figure>"
            "</div>%s</details>"
            % (caption, truth, esc(frame.belief_label), belief, table))


def _summary(result: MatchResult, recorder: Recorder) -> str:
    parts = ["<h2>判定</h2>"]
    parts.append("<p><span class='verdict %s'>%s</span></p>"
                 % ("ok" if result.understood else "bad",
                    "理解" if result.understood else "不理解"))
    rows = []
    for name in STAGES:
        if name in result.stages:
            stage = result.stages[name]
            rows.append("<li><b>%s</b>：%d/%d · %s%s</li>" % (
                esc(stage.label), stage.correct, stage.total,
                "理解" if stage.understood else "不理解",
                ("（第 %d 个操作后两份状态不一致）" % stage.diverged_at)
                if stage.diverged_at else "",
            ))
    parts.append("<ul>%s</ul>" % "".join(rows))
    if result.protocol_errors:
        parts.append("<p class='sub'>整次测试作废的协议错误：</p><ul>%s</ul>"
                     % "".join("<li>%s</li>" % esc(r) for r in result.protocol_errors))
    if result.reasons:
        parts.append("<p class='sub'>逐条错处：</p><ul>%s</ul>"
                     % "".join("<li>%s</li>" % esc(r) for r in result.reasons))
    if result.skipped_questions:
        parts.append("<p class='sub'>跳过的无效题：</p><ul>%s</ul>"
                     % "".join("<li>%s</li>" % esc(s) for s in result.skipped_questions))
    return "".join(parts)


def save(html_text: str, path: str) -> str:
    import os
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html_text)
    return path
