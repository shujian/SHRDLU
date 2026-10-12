"""Stage 9 acceptance: watching a match, and interfering with it.

Three things the viewer must get right:

* it shows **both** states — the truth and the testee's belief — and marks where
  they disagree, because that disagreement is the measurement;
* it pauses between exchanges and does not change the outcome by doing so;
* the operator can put an extra question or issue an extra instruction, and an
  extra **question** must not touch the official record while an extra
  **instruction** genuinely moves the world.
"""

from __future__ import annotations

import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)  # project root
sys.path.insert(0, HERE)  # tests dir

from shrdlu import protocol, snapshot  # noqa: E402
from shrdlu.testee.example import ExampleTestee  # noqa: E402
from shrdlu.env import host, scenario  # noqa: E402
from shrdlu.env.cli import play_main  # noqa: E402
from shrdlu.world import World  # noqa: E402


def first_version():
    return scenario.load("first-version")


def row_for(rows, ident):
    """The table row whose first column is exactly ``ident``.

    Matching on a bare letter as a substring would match half the table
    ("c" appears in "cube", in "on the table", ...), so the id column is
    compared exactly.
    """
    for row in rows:
        parts = row.split()
        if parts and parts[0] == ident:
            return row
    return None


class TestStateDisplay(unittest.TestCase):
    def test_position_of_covers_every_form(self):
        world = first_version().world()
        self.assertEqual(play_main.position_of(world, "a"), "on b")
        self.assertEqual(play_main.position_of(world, "b"), "on the table")
        world.set_pos("a", ("hand",))
        self.assertEqual(play_main.position_of(world, "a"), "in hand")
        world.set_pos("a", ("table",))
        self.assertEqual(play_main.position_of(world, "a"), "on the table")

    def test_missing_object_is_reported_not_crashed(self):
        self.assertEqual(play_main.position_of(first_version().world(), "nope"), "(不存在)")

    def test_agreement_is_not_marked(self):
        world = first_version().world()
        model = snapshot.from_snapshot(snapshot.to_snapshot(world))
        rows = "\n".join(play_main.state_table(world, model))
        self.assertNotIn("不一致", rows)

    def test_disagreement_is_marked(self):
        world = first_version().world()
        model = snapshot.from_snapshot(snapshot.to_snapshot(world))
        model.set_pos("a", ("table",))
        rows = play_main.state_table(world, model)
        marked = [r for r in rows if "不一致" in r]
        self.assertEqual(len(marked), 1)
        self.assertTrue(marked[0].split()[0] == "a", marked[0])

    def test_a_model_missing_an_object_is_marked(self):
        world = first_version().world()
        model = snapshot.from_snapshot(snapshot.to_snapshot(world))
        model.remove("c")
        rows = play_main.state_table(world, model)
        row = row_for(rows, "c")
        self.assertIsNotNone(row)
        self.assertIn("<<<", row)
        self.assertIn("(不存在)", row)

    def test_no_model_says_so(self):
        rows = play_main.state_table(first_version().world(), None)
        self.assertTrue(any("看不到" in r for r in rows))


class TestViewerPauses(unittest.TestCase):
    def run_viewer(self, commands, impl="example", **kwargs):
        console = play_main.ScriptedConsole(commands)
        out = io.StringIO()
        code = play_main.main(
            ["--scenario", "first-version", "--testee", impl],
            console=console, out=out, **kwargs
        )
        return code, out.getvalue(), console

    def test_it_stops_once_per_exchange(self):
        # the opening observation + 4 instructions + the bank asked twice
        _, _, console = self.run_viewer([""] * 40)
        self.assertEqual(console.prompts, 1 + 4 + 10 + 10)

    def test_pausing_does_not_change_the_outcome(self):
        straight = host.run(first_version(), ExampleTestee())
        code, text, _ = self.run_viewer([""] * 40)
        self.assertEqual(code, 1)                 # 最小示例不理解
        self.assertIn("verdict:", text)
        self.assertEqual(len(straight.steps), 24)

    def test_a_testee_in_another_process_can_be_watched(self):
        """The comparison is the env's, so a subprocess testee works too."""
        command = "%s -m shrdlu.testee.cli.testee_main" % sys.executable
        code, text, console = self.run_viewer([""] * 40, impl=command)
        self.assertEqual(code, 1)
        self.assertIn("verdict: not_understood", text)
        self.assertEqual(console.prompts, 25)

    def test_a_bye_ends_the_session(self):
        code, text, _ = self.run_viewer(["x"])
        self.assertEqual(code, 130)
        self.assertIn("中途结束", text)

    def test_an_exhausted_console_ends_the_session(self):
        code, _, _ = self.run_viewer([])
        self.assertEqual(code, 130)

    def test_help_is_shown_on_request(self):
        _, text, _ = self.run_viewer(["h", "x"])
        self.assertIn("额外问一句", text)

    def test_state_can_be_redisplayed(self):
        _, text, _ = self.run_viewer(["s", "x"])
        self.assertGreaterEqual(text.count("世界的当前状态与"), 2)

    def test_an_unknown_command_is_politely_ignored(self):
        _, text, _ = self.run_viewer(["blah", "x"])
        self.assertIn("看不懂", text)


class TestInterference(unittest.TestCase):
    def run_with(self, commands):
        console = play_main.ScriptedConsole(commands)
        out = io.StringIO()
        code = play_main.main(["--scenario", "first-version"],
                              console=console, out=out)
        return code, out.getvalue()

    def test_an_injected_question_is_answered_and_not_recorded(self):
        code, text = self.run_with([
            "q Is the green cube on the red cube?",   # at the opening pause
            "x",
        ])
        self.assertIn("临时提问", text)
        self.assertIn("答错", text)
        self.assertIn("临时试探 1 次", text)

    def test_an_injected_question_reports_the_right_answer_when_wrong(self):
        # a frozen testee does not track; ask about something its model got wrong
        console = play_main.ScriptedConsole([
            "",                                    # carry on past the opening
            "c Put the blue pyramid on the blue cube",   # make a change
            "q Is the blue pyramid on the blue cube?",
            "x",
        ])
        out = io.StringIO()
        play_main.main(["--scenario", "first-version", "--testee", "example"],
                       console=console, out=out)
        text = out.getvalue()
        self.assertIn("答错", text)
        self.assertIn("正确答案是 yes", text)

    def test_an_injected_instruction_moves_the_world(self):
        console = play_main.ScriptedConsole([
            "c Put the green cube on the blue cube",
            "s",                                    # redraw to see it
            "x",
        ])
        out = io.StringIO()
        play_main.main(["--scenario", "first-version"], console=console, out=out)
        text = out.getvalue()
        self.assertIn("会真的改变世界", text)
        # the redrawn state must show the green cube on the blue cube
        self.assertIn("on c", text)

    def test_a_bad_question_is_explained_not_raised(self):
        _, text = self.run_with(["q Fly me to the moon", "x"])
        self.assertIn("这不是我能问的问句", text)

    def test_an_unanswerable_question_is_explained(self):
        _, text = self.run_with(["q Is the cube on the table?", "x"])
        self.assertIn("对当前状态问不了", text)

    def test_a_bad_command_is_explained_not_raised(self):
        _, text = self.run_with(["c Fling the cube", "x"])
        self.assertIn("这不是我能下的指令", text)

    def test_an_unresolvable_command_is_explained(self):
        _, text = self.run_with(["c Put the cube on the red cube", "x"])
        self.assertIn("指不到唯一对象", text)

    def test_an_empty_probe_prints_usage(self):
        _, text = self.run_with(["q", "c", "x"])
        self.assertIn("用法", text)


class TestStepCallback(unittest.TestCase):
    def test_the_callback_sees_the_observation_then_every_step(self):
        events = []
        host.run(first_version(), ExampleTestee(), on_step=events.append)
        self.assertEqual(len(events), 25)
        self.assertEqual(events[0].phase, "observe")
        self.assertIsNone(events[0].step)
        self.assertEqual([e.phase for e in events[1:11]], ["question"] * 10)
        self.assertEqual([e.phase for e in events[11:15]], ["instruction"] * 4)
        self.assertEqual([e.phase for e in events[15:]], ["question"] * 10)

    def test_the_callback_says_which_stage_each_step_belongs_to(self):
        events = []
        host.run(first_version(), ExampleTestee(), on_step=events.append)
        self.assertEqual([e.stage for e in events[1:11]], ["initial"] * 10)
        self.assertEqual([e.stage for e in events[11:15]], ["operations"] * 4)
        self.assertEqual([e.stage for e in events[15:]], ["final"] * 10)
        self.assertEqual(events[0].stage, "")

    def test_the_callback_can_see_both_of_the_envs_states(self):
        events = []
        host.run(first_version(), ExampleTestee(), on_step=events.append)
        self.assertIsInstance(events[-1].second, World)
        # 示例实现从不执行操作，所以两份状态不同：它们本来就各归各的
        self.assertNotEqual(snapshot.to_snapshot(events[-1].second),
                            snapshot.to_snapshot(events[-1].truth))

    def test_the_callback_can_see_the_truth_and_the_testee(self):
        seen = []
        player = ExampleTestee()
        host.run(first_version(), player, on_step=seen.append)
        self.assertIsInstance(seen[-1].truth, World)
        self.assertIs(seen[-1].testee, player)
        self.assertIsNotNone(getattr(seen[-1].testee, "state", None))

    def test_the_callback_is_optional(self):
        result = host.run(first_version(), ExampleTestee())
        self.assertEqual(result.verdict, "not_understood")

    def test_indexes_are_sequential(self):
        events = []
        host.run(first_version(), ExampleTestee(), on_step=events.append)
        self.assertEqual([e.index for e in events], list(range(25)))


class TestNoPause(unittest.TestCase):
    def test_no_pause_plays_straight_through(self):
        out = io.StringIO()
        code = play_main.main(["--scenario", "first-version", "--no-pause"], out=out)
        self.assertEqual(code, 1)
        self.assertIn("verdict: not_understood", out.getvalue())


class TestGenerateMode(unittest.TestCase):
    def test_generate_builds_a_scene_and_an_exam(self):
        out = io.StringIO()
        console = play_main.ScriptedConsole(["x"])
        code = play_main.main(["--seed", "3"], console=console, out=out)
        text = out.getvalue()
        self.assertIn("条指令", text)
        self.assertIn("道题", text)
        self.assertEqual(code, 130)  # stopped early on request


if __name__ == "__main__":
    unittest.main()
