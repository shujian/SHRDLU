"""Stage 2 acceptance: the env main loop, driven by a scripted fake testee.

The point of this stage is the *plumbing*, not intelligence: the scripted
testee is a lookup table that replays pre-recorded replies and understands
nothing.  If the host judges its behaviour correctly, the harness works.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # project root
sys.path.insert(0, HERE)                   # tests dir

from support import load_scenario  # noqa: E402

from shrdlu import ops, protocol, questions, snapshot  # noqa: E402
from shrdlu.env import host, scenario  # noqa: E402


class ScriptedTestee:
    """Replays a fixed list of replies and remembers what it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def handle(self, message: str) -> str:
        self.seen.append(message)
        if not self.replies:
            raise AssertionError("script exhausted; host sent an extra message")
        return self.replies.pop(0)


class RaisingTestee:
    """A testee that blows up on everything."""

    def handle(self, message: str) -> str:
        raise RuntimeError("boom")


def correct_script(sc: scenario.Scenario):
    """Replies a perfectly-behaved testee would give, computed from the truth.

    This is deliberately not "understanding": it is a lookup table built with
    privileged access, used only to exercise the host.  The three stages
    (protocol §5) put the question bank **twice** in the list: once about the
    initial state, once about the state the instructions produced.
    """
    world = sc.world()
    replies = [""]  # observe is fire-and-forget
    for question in sc.questions:
        replies.append(protocol.answer(questions.evaluate(question, world).text()))
    for inst in sc.instructions:
        verdict = ops.check(world, inst.op, list(inst.args))
        if verdict.legal:
            replies.append(protocol.action(inst.op, list(inst.args)))
            ops.apply(world, inst.op, list(inst.args))
        else:
            replies.append(protocol.refuse(verdict.reason or "no"))
    for question in sc.questions:
        replies.append(protocol.answer(questions.evaluate(question, world).text()))
    return replies


class TestHappyPath(unittest.TestCase):
    def setUp(self):
        self.sc = scenario.load("first-version")

    def test_correct_play_is_judged_understood(self):
        result = host.run(self.sc, ScriptedTestee(correct_script(self.sc)))
        self.assertEqual(result.verdict, "understood", result.render())
        self.assertEqual(result.reasons, [])
        self.assertIsNone(result.illegal_attempt)
        self.assertEqual(result.correct, 2 * len(self.sc.questions))
        self.assertTrue(all(s.ok for s in result.steps))

    def test_every_stage_is_judged_on_its_own(self):
        result = host.run(self.sc, ScriptedTestee(correct_script(self.sc)))
        self.assertEqual(result.stage("initial").correct, len(self.sc.questions))
        self.assertEqual(result.stage("operations").correct, len(self.sc.instructions))
        self.assertEqual(result.stage("final").correct, len(self.sc.questions))
        self.assertTrue(all(result.stage(name).understood for name in host.STAGES))

    def test_final_state_matches_the_recorded_expectation(self):
        result = host.run(self.sc, ScriptedTestee(correct_script(self.sc)))
        expected = snapshot.from_snapshot(self.sc.expected_final_state)
        self.assertEqual(result.final_state, snapshot.to_snapshot(expected))
        self.assertEqual(result.second_state, result.final_state)
        self.assertEqual(result.final_drift, [])

    def test_host_sends_observe_then_questions_then_instructions_then_questions(self):
        testee = ScriptedTestee(correct_script(self.sc))
        host.run(self.sc, testee)
        kinds = [protocol.decode(m)["type"] for m in testee.seen]
        questions = len(self.sc.questions)
        commands = len(self.sc.instructions)
        self.assertEqual(kinds[0], "observe")
        self.assertEqual(kinds[1:1 + questions], ["question"] * questions)
        self.assertEqual(kinds[1 + questions:1 + questions + commands],
                         ["command"] * commands)
        self.assertEqual(kinds[1 + questions + commands:],
                         ["question"] * questions)

    def test_generated_instruction_text_matches_the_scenario(self):
        testee = ScriptedTestee(correct_script(self.sc))
        host.run(self.sc, testee)
        sent = [protocol.message_text(protocol.decode(m))
                for m in testee.seen if protocol.decode(m)["type"] == "command"]
        self.assertEqual(sent, [i.text for i in self.sc.instructions])

    def test_generated_question_text_matches_the_scenario(self):
        testee = ScriptedTestee(correct_script(self.sc))
        host.run(self.sc, testee)
        sent = [protocol.message_text(protocol.decode(m))
                for m in testee.seen if protocol.decode(m)["type"] == "question"]
        # the same bank is asked once per question stage, in the same order
        self.assertEqual(sent, self.sc.question_text * 2)

    def test_recorded_truth_matches_the_evaluator(self):
        # the scenario file also records the expected answer; check it agrees
        world = self.sc.world()
        for inst in self.sc.instructions:
            if ops.check(world, inst.op, list(inst.args)).legal:
                ops.apply(world, inst.op, list(inst.args))
        for question, recorded in zip(self.sc.questions, self.sc.question_answer):
            with self.subTest(question=questions.render(question)):
                self.assertEqual(questions.evaluate(question, world).text(), recorded)


class TestInstructionJudging(unittest.TestCase):
    """The 2x2 table of protocol §5.4."""

    def setUp(self):
        self.sc = scenario.load("first-version")

    def script_with(self, index: int, replacement: str):
        """The correct script, with reply #index (0 = observe) replaced."""
        script = correct_script(self.sc)
        script[index] = replacement
        return script

    def commands(self, result):
        """The instruction steps of a record, in order."""
        return [s for s in result.steps if s.kind == "command"]

    def first_command(self):
        """Script index of the first instruction (the bank is asked first)."""
        return 1 + len(self.sc.questions)

    def test_refusing_a_legal_instruction_fails(self):
        # the first instruction is legal
        testee = ScriptedTestee(self.script_with(self.first_command(),
                                                 protocol.refuse("no")))
        result = host.run(self.sc, testee)
        self.assertEqual(result.verdict, "not_understood")
        first = self.commands(result)[0]
        self.assertFalse(first.ok)
        self.assertIn("refused a legal instruction", first.note)
        self.assertFalse(result.stage("operations").understood)

    def test_refusing_an_illegal_instruction_is_correct(self):
        # the third instruction, "Pick up the red cube", is illegal
        result = host.run(self.sc, ScriptedTestee(correct_script(self.sc)))
        third = self.commands(result)[2]
        self.assertTrue(third.ok)
        self.assertEqual(third.received, "refuse")

    def test_executing_an_illegal_instruction_fails_and_is_recorded(self):
        script = self.script_with(self.first_command() + 2,
                                  protocol.action("pick_up", ["b"]))
        result = host.run(self.sc, ScriptedTestee(script))
        self.assertEqual(result.verdict, "not_understood")
        self.assertIsNotNone(result.illegal_attempt)
        self.assertIn("illegal", result.illegal_attempt)
        self.assertFalse(self.commands(result)[2].ok)

    def test_illegal_attempt_does_not_change_the_truth(self):
        # the red cube must still support the green cube afterwards
        script = self.script_with(self.first_command() + 2,
                                  protocol.action("pick_up", ["b"]))
        result = host.run(self.sc, ScriptedTestee(script))
        final = snapshot.from_snapshot(result.final_state)
        self.assertEqual(final.pos_of("e"), ("on", "a"))

    def test_acting_on_the_wrong_object_fails(self):
        script = self.script_with(self.first_command(),
                                  protocol.action("pick_up", ["e"]))
        result = host.run(self.sc, ScriptedTestee(script))
        first = self.commands(result)[0]
        self.assertFalse(first.ok)
        self.assertIn("differently", first.note)
        # the second state followed its call, so the two states now differ
        self.assertNotEqual(result.second_state, result.final_state)
        self.assertEqual(result.stage("operations").diverged_at, 1)
        self.assertTrue(first.drift)

    def test_truth_follows_the_script_even_when_the_testee_is_wrong(self):
        # wrong on every legal instruction; truth must still end up as scripted
        script = correct_script(self.sc)
        first = self.first_command()
        for offset in (0, 1, 3):
            script[first + offset] = protocol.refuse("nope")
        result = host.run(self.sc, ScriptedTestee(script))
        expected = snapshot.from_snapshot(self.sc.expected_final_state)
        self.assertEqual(result.final_state, snapshot.to_snapshot(expected))


class TestQuestionJudging(unittest.TestCase):
    def setUp(self):
        self.sc = scenario.load("first-version")

    def test_a_wrong_answer_fails_the_match(self):
        # the first question whose answer is "yes" in the initial state
        world = self.sc.world()
        offset = next(i for i, q in enumerate(self.sc.questions)
                      if questions.evaluate(q, world).text() == "yes")
        script = correct_script(self.sc)
        script[1 + offset] = protocol.answer("no")
        result = host.run(self.sc, ScriptedTestee(script))
        self.assertEqual(result.verdict, "not_understood")
        self.assertFalse(result.steps[offset].ok)
        self.assertIn("expected yes", result.steps[offset].note)
        self.assertEqual(result.correct, 2 * len(self.sc.questions) - 1)
        self.assertFalse(result.stage("initial").understood)
        self.assertTrue(result.stage("final").understood)

    def test_synonyms_are_accepted(self):
        script = correct_script(self.sc)
        # find the size question by its text rather than by counting: the bank
        # is hand-written and its order is not a contract
        offset = next(i for i, q in enumerate(self.sc.question_text)
                      if q.startswith("How big"))
        script[1 + offset] = protocol.answer("little")
        result = host.run(self.sc, ScriptedTestee(script))
        self.assertTrue(result.steps[offset].ok, result.render())

    def test_a_refusal_to_answer_counts_as_wrong(self):
        script = correct_script(self.sc)
        script[1] = protocol.refuse("I don't know")
        result = host.run(self.sc, ScriptedTestee(script))
        self.assertEqual(result.verdict, "not_understood")

    def test_invalid_questions_are_skipped_not_counted(self):
        mini = scenario.from_json({
            "name": "mini",
            "state": {
                "objects": [
                    {"id": "a", "kind": "cube", "color": "red", "size": "big",
                     "pos": ["table"]},
                    {"id": "b", "kind": "cube", "color": "blue", "size": "big",
                     "pos": ["table"]},
                ],
                "hand": None,
            },
            "instructions": [],
            "questions": [
                {"type": "rel", "desc": {"quant": "the", "kind": "cube"},
                 "rel": {"name": "on_table"},
                 "text": "Is the cube on the table?", "answer": "yes"},
            ],
        })
        result = host.run(mini, ScriptedTestee([""]))
        self.assertEqual(len(result.asked), 0)
        # dropped in both question stages, counted in neither
        self.assertEqual(len(result.skipped_questions), 2)
        self.assertIn("matches 2 objects", result.skipped_questions[0])
        self.assertEqual(result.stage("initial").total, 0)
        self.assertEqual(result.stage("final").total, 0)


class TestRobustness(unittest.TestCase):
    def setUp(self):
        self.sc = scenario.load("first-version")

    def test_a_raising_testee_does_not_crash_the_env(self):
        result = host.run(self.sc, RaisingTestee())
        self.assertEqual(result.verdict, "not_understood")
        self.assertTrue(any("raised" in r for r in result.reasons))

    def test_garbage_replies_are_recorded_not_fatal(self):
        script = [""] + ["not json at all"] * 20
        result = host.run(self.sc, ScriptedTestee(script))
        self.assertEqual(result.verdict, "not_understood")
        self.assertTrue(any("bad reply" in r for r in result.reasons))

    def test_exhausted_script_is_reported(self):
        result = host.run(self.sc, ScriptedTestee([""]))
        self.assertEqual(result.verdict, "not_understood")

    def test_result_is_json_serialisable(self):
        result = host.run(self.sc, ScriptedTestee(correct_script(self.sc)))
        text = json.dumps(result.to_json(), ensure_ascii=False)
        self.assertIn("first-version", text)

    def test_protocol_rejects_unknown_types(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.decode('{"type": "sing"}')
        with self.assertRaises(protocol.ProtocolError):
            protocol.decode("")


if __name__ == "__main__":
    unittest.main()
