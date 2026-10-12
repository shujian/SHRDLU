"""Stage 11 acceptance: the HTML report.

The report is a **read-only view** of a finished match, so the things worth
testing are that it is genuinely self-contained, that it says what happened, and
that it cannot be turned into an injection vector by a testee's own words.

It is not part of the protocol and does not judge; a report that started
influencing the result would be a bug, not a feature.
"""

from __future__ import annotations

import io
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from shrdlu import protocol, snapshot  # noqa: E402
from shrdlu.env import host, scenario, webreport  # noqa: E402
from shrdlu.env.cli import report_main  # noqa: E402

BASE = scenario.load("first-version")


def run(impl="example", record=True):
    player = report_main.build_testee(impl)
    recorder = webreport.Recorder(testee_label=impl)
    result = host.run(BASE, player, on_step=recorder)
    return result, recorder


class RudeTestee:
    """Answers with markup, to prove the report escapes what a testee says."""

    def __init__(self) -> None:
        self.model = None

    def handle(self, message: str) -> str:
        kind = protocol.decode(message).get("type")
        if kind == "observe":
            self.model = snapshot.from_snapshot(protocol.decode(message)["state"])
            return ""
        if kind == "command":
            return protocol.refuse("no")
        return protocol.answer("<script>alert(1)</script>")


class TestSelfContained(unittest.TestCase):
    def setUp(self):
        self.result, self.recorder = run()
        self.page = webreport.build(self.result, self.recorder, scenario_=BASE)

    def test_there_is_no_javascript_at_all(self):
        self.assertNotIn("<script", self.page.lower())
        self.assertNotIn("javascript:", self.page.lower())

    def test_nothing_is_fetched_from_outside(self):
        refs = [r for r in re.findall(r"(?:src|href)=['\"]([^'\"]+)", self.page)]
        self.assertEqual(refs, [])
        self.assertNotIn("@import", self.page)

    def test_the_scenes_are_inline_svg(self):
        self.assertIn("<svg", self.page)
        self.assertIn("</svg>", self.page)

    def test_it_is_a_complete_document(self):
        self.assertTrue(self.page.startswith("<!DOCTYPE html>"))
        self.assertIn("<meta charset='utf-8'>", self.page)
        self.assertTrue(self.page.rstrip().endswith("</html>"))

    def test_it_says_what_it_is(self):
        self.assertIn("仅从测试记录重放，不参与判分", self.page)


class TestWhatItSays(unittest.TestCase):
    def test_every_exchange_appears(self):
        result, recorder = run()
        page = webreport.build(result, recorder, scenario_=BASE)
        self.assertEqual(page.count("<li class='step"), len(result.steps))
        for step in result.steps:
            self.assertIn(step.sent, page)

    def test_the_verdict_and_score_are_shown(self):
        result, recorder = run()
        page = webreport.build(result, recorder, scenario_=BASE)
        self.assertIn("不理解", page)
        self.assertIn("/10", page)
        # each stage reports its own conclusion
        for name in host.STAGES:
            self.assertIn(host.STAGE_LABELS[name], page)

    def test_questions_are_marked_reason_or_recall(self):
        result, recorder = run()
        page = webreport.build(result, recorder, scenario_=BASE)
        self.assertIn("badge reason", page)
        self.assertIn("badge recall", page)

    def test_a_wrong_testee_shows_where_it_drifted(self):
        # colorblind refuses a legal instruction, so the state its calls produce
        # stops matching the scripted truth from that step on
        result, recorder = run("example")
        page = webreport.build(result, recorder, scenario_=BASE)
        self.assertIn("处不一致", page)
        self.assertIn(webreport.SECOND_STATE_LABEL, page)

    def test_the_raw_record_is_embedded(self):
        result, recorder = run()
        page = webreport.build(result, recorder, scenario_=BASE)
        self.assertIn("完整记录", page)
        # the JSON is escaped like any other text, quotes included
        self.assertIn("&quot;verdict&quot;", page)
        self.assertIn("&quot;first-version&quot;", page)


class TestEscaping(unittest.TestCase):
    """A testee's own words must never become markup."""

    def page_for_rude_testee(self):
        recorder = webreport.Recorder()
        result = host.run(BASE, RudeTestee(), on_step=recorder)
        return webreport.build(result, recorder, scenario_=BASE), result

    def test_a_testee_cannot_inject_markup_through_its_answers(self):
        page, result = self.page_for_rude_testee()
        self.assertNotIn("<script", page.lower())
        self.assertIn("&lt;script&gt;", page)

    def test_the_raw_answer_is_still_readable_when_escaped(self):
        page, result = self.page_for_rude_testee()
        self.assertIn("alert(1)", page)

    def test_a_picture_containing_script_is_refused(self):
        result, recorder = run()
        recorder._pictures = ["<svg><script>alert(1)</script></svg>"]
        with self.assertRaises(webreport.ReportError):
            webreport.build(result, recorder, scenario_=BASE)


class TestPictures(unittest.TestCase):
    def test_identical_states_share_one_picture(self):
        result, recorder = run()
        self.assertLess(len(recorder.pictures), len(recorder.frames))

    def test_every_frame_points_at_a_real_picture(self):
        result, recorder = run()
        for frame in recorder.frames:
            self.assertGreaterEqual(frame.truth_svg, 0)
            self.assertLess(frame.truth_svg, len(recorder.pictures))
            if frame.model_svg >= 0:
                self.assertLess(frame.model_svg, len(recorder.pictures))

    def test_the_report_is_deterministic(self):
        first = webreport.build(*run(), scenario_=BASE)
        second = webreport.build(*run(), scenario_=BASE)
        self.assertEqual(first, second)

    def test_a_testee_without_a_private_model_is_still_compared(self):
        """The comparison no longer needs the testee to be in this process.

        The env maintains the second state itself, so a testee that keeps no
        symbolic model at all — even one in another process — gets the same
        side-by-side view.
        """
        class NoModel:
            def handle(self, message):
                kind = protocol.decode(message).get("type")
                if kind == "observe":
                    return ""
                if kind == "command":
                    return protocol.refuse("no")
                return protocol.answer("yes")

        recorder = webreport.Recorder()
        result = host.run(BASE, NoModel(), on_step=recorder)
        page = webreport.build(result, recorder, scenario_=BASE)
        self.assertIn("<svg", page)
        self.assertIn(webreport.SECOND_STATE_LABEL, page)
        # it refused every instruction, so the states drifted apart early
        self.assertIn("处不一致", page)

    def test_frames_carry_the_stage_they_belong_to(self):
        result, recorder = run()
        stages = [f.stage for f in recorder.frames]
        self.assertEqual(stages[0], "")
        self.assertEqual(stages[1:11], ["initial"] * 10)
        self.assertEqual(stages[11:15], ["operations"] * 4)
        self.assertEqual(stages[15:], ["final"] * 10)


class TestDifferences(unittest.TestCase):
    def test_a_matching_model_has_no_differences(self):
        world = BASE.world()
        model = snapshot.from_snapshot(snapshot.to_snapshot(world))
        self.assertEqual(webreport.differences(world, model), [])

    def test_a_drifted_model_lists_every_disagreement(self):
        world = BASE.world()
        model = snapshot.from_snapshot(snapshot.to_snapshot(world))
        model.set_pos("a", ("table",))
        found = webreport.differences(world, model)
        self.assertEqual([row[0] for row in found], ["a"])
        self.assertEqual(found[0][1], "on b")
        self.assertEqual(found[0][2], "on the table")

    def test_a_missing_object_is_reported_as_missing(self):
        world = BASE.world()
        model = snapshot.from_snapshot(snapshot.to_snapshot(world))
        model.remove("c")
        found = webreport.differences(world, model)
        self.assertEqual(found[0][2], "(不存在)")

    def test_no_model_means_no_comparison(self):
        self.assertEqual(webreport.differences(BASE.world(), None), [])


class TestReportCli(unittest.TestCase):
    def test_it_writes_a_report_and_says_where(self):
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "r.html")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = report_main.main(["--scenario", "first-version", "--out", path])
            self.assertEqual(code, 1)                 # 最小示例不理解
            self.assertIn("open", out.getvalue())
            self.assertTrue(os.path.exists(path))
            with open(path, encoding="utf-8") as handle:
                page = handle.read()
        self.assertIn("<!DOCTYPE html>", page)

    def test_a_wrong_testee_exits_nonzero_but_still_writes(self):
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "r.html")
            with contextlib.redirect_stdout(io.StringIO()):
                code = report_main.main(["--scenario", "first-version",
                                         "--testee", "example", "--out", path,
                                         "--quiet"])
            self.assertEqual(code, 1)
            self.assertTrue(os.path.exists(path))

    def test_an_external_testee_can_be_reported(self):
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "r.html")
            with contextlib.redirect_stdout(io.StringIO()):
                code = report_main.main([
                    "--scenario", "first-version",
                    "--testee", "%s -m shrdlu.testee.cli.testee_main" % sys.executable,
                    "--out", path, "--quiet"])
            self.assertEqual(code, 1)                 # 最小示例必然不理解
            self.assertTrue(os.path.exists(path))

    def test_a_generated_exam_can_be_reported(self):
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "r.html")
            with contextlib.redirect_stdout(io.StringIO()):
                code = report_main.main(["--seed", "3",
                                         "--out", path, "--quiet"])
            self.assertEqual(code, 1)
            with open(path, encoding="utf-8") as handle:
                page = handle.read()
        self.assertIn("种子 <b>3</b>", page)


if __name__ == "__main__":
    unittest.main()
