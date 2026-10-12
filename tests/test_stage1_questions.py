"""Stage 1 acceptance: the env-side question mechanism.

The centrepiece is :class:`TestSampleQuestions`, which reproduces the ten
questions of docs/设计协议.md §7.3 verbatim — both their English surface
form and their truth value after the §8.2 instruction sequence.
"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # project root
sys.path.insert(0, HERE)                   # tests dir

from support import after_instructions, load_scenario, scene_world  # noqa: E402

from shrdlu import ops, questions, snapshot  # noqa: E402
from shrdlu.env import answers  # noqa: E402
from shrdlu.questions import AllQ, Answer, AttrQ, CountQ, Desc, ExistsQ, Rel, RelQ  # noqa: E402

SCENARIO = load_scenario()
SAMPLE = SCENARIO["state"]

#: Convenience descriptions reused across the sample questions.
GREEN = Desc(quant="the", color="green", kind="cube")
RED = Desc(quant="the", color="red", kind="cube")
BLUE_CUBE = Desc(quant="the", color="blue", kind="cube")
BLUE_PYRAMID = Desc(quant="the", color="blue", kind="pyramid")
THE_PYRAMID = Desc(quant="the", kind="pyramid")
THE_BALL = Desc(quant="the", color="yellow", kind="ball")


class TestSampleQuestions(unittest.TestCase):
    """docs/设计协议.md §7.3, reproduced exactly."""

    #: (question, expected English, expected answer text)
    CASES = [
        (RelQ(BLUE_PYRAMID, Rel("on", BLUE_CUBE)),
         "Is the blue pyramid on the blue cube?", "yes"),
        (RelQ(GREEN, Rel("clear")),
         "Is the green cube clear?", "no"),
        (RelQ(THE_BALL, Rel("on", GREEN)),
         "Is the yellow ball on the green cube?", "yes"),
        (RelQ(THE_PYRAMID, Rel("supported")),
         "Is the pyramid supported?", "yes"),
        (AttrQ(BLUE_PYRAMID, "color"),
         "What color is the blue pyramid?", "blue"),
        (AttrQ(GREEN, "size"),
         "How big is the green cube?", "small"),
        (AttrQ(THE_BALL, "kind"),
         "What shape is the yellow ball?", "ball"),
        (CountQ(Desc(kind="ball"), Rel("on_table")),
         "How many balls are on the table?", "0"),
        (AllQ(Desc(kind="cube"), Rel("on_table")),
         "Are all cubes on the table?", "no"),
        (ExistsQ(Desc(kind="cube", color="red"), Rel("on_table")),
         "Is there a red cube on the table?", "yes"),
    ]

    def setUp(self):
        self.world = after_instructions()

    def test_every_sample_renders_as_specified(self):
        for question, english, _ in self.CASES:
            with self.subTest(english=english):
                self.assertEqual(questions.render(question), english)

    def test_every_sample_evaluates_to_the_recorded_truth(self):
        for question, english, expected in self.CASES:
            with self.subTest(english=english):
                got = questions.evaluate(question, self.world)
                self.assertEqual(got.text(), expected)

    def test_every_sample_answer_is_graded_correct(self):
        for question, english, expected in self.CASES:
            with self.subTest(english=english):
                truth = questions.evaluate(question, self.world)
                self.assertTrue(answers.matches(expected, truth))

    def test_no_sample_is_an_invalid_question(self):
        for question, english, _ in self.CASES:
            with self.subTest(english=english):
                self.assertIsNone(questions.validate(question, self.world))


class TestInvalidQuestions(unittest.TestCase):
    """docs/设计协议.md §7.4."""

    def setUp(self):
        self.world = after_instructions()

    def test_ambiguous_definite_description_is_rejected(self):
        # "the cube" matches three objects
        bad = RelQ(Desc(quant="the", kind="cube"), Rel("on_table"))
        self.assertEqual(questions.render(bad), "Is the cube on the table?")
        reason = questions.validate(bad, self.world)
        self.assertIsNotNone(reason)
        self.assertIn("matches 3 objects", reason)

    def test_empty_definite_description_is_rejected(self):
        bad = AttrQ(Desc(quant="the", color="purple", kind="cube"), "color")
        self.assertIsNotNone(questions.validate(bad, self.world))

    def test_all_question_over_empty_set_is_rejected(self):
        bad = AllQ(Desc(color="purple", kind="cube"), Rel("on_table"))
        self.assertIsNotNone(questions.validate(bad, self.world))

    def test_exists_over_empty_set_is_fine_and_false(self):
        q = ExistsQ(Desc(color="purple", kind="cube"), Rel("on_table"))
        self.assertIsNone(questions.validate(q, self.world))
        self.assertEqual(questions.evaluate(q, self.world).text(), "no")

    def test_count_over_empty_set_is_fine_and_zero(self):
        q = CountQ(Desc(color="purple", kind="cube"), Rel("on_table"))
        self.assertIsNone(questions.validate(q, self.world))
        self.assertEqual(questions.evaluate(q, self.world).text(), "0")


class TestRelationSemantics(unittest.TestCase):
    """``on`` must mean direct contact, per protocol §3.2."""

    def test_on_is_direct_not_transitive(self):
        w = snapshot.from_snapshot(SAMPLE)
        # a is directly on b
        self.assertTrue(questions.evaluate(RelQ(GREEN, Rel("on", RED)), w).value)
        # but "on the table" is false: it is on the red cube, not the table
        self.assertFalse(questions.evaluate(RelQ(GREEN, Rel("on_table")), w).value)

    def test_three_high_stack_is_not_on_the_bottom(self):
        w = snapshot.from_snapshot({
            "objects": [
                {"id": "a", "kind": "cube", "color": "red", "size": "big",
                 "pos": ["table"]},
                {"id": "b", "kind": "cube", "color": "green", "size": "small",
                 "pos": ["on", "a"]},
                {"id": "c", "kind": "cube", "color": "blue", "size": "small",
                 "pos": ["on", "b"]},
            ],
            "hand": None,
        })
        c = Desc(quant="the", kind="cube", color="blue")
        b = Desc(quant="the", kind="cube", color="green")
        a = Desc(quant="the", kind="cube", color="red")
        self.assertTrue(questions.evaluate(RelQ(c, Rel("on", b)), w).value)
        self.assertFalse(questions.evaluate(RelQ(c, Rel("on", a)), w).value)
        self.assertTrue(questions.evaluate(RelQ(c, Rel("supported")), w).value)


class TestRendering(unittest.TestCase):
    def test_articles(self):
        self.assertEqual(Desc(quant="a", color="red", kind="cube").render(), "a red cube")
        self.assertEqual(Desc(quant="a", color="orange", kind="cube").render(), "an orange cube")

    def test_plural_and_bare_plural(self):
        self.assertEqual(Desc(quant="all", kind="ball").render(), "all balls")
        self.assertEqual(Desc(kind="pyramid").render_bare_plural(), "pyramids")
        self.assertEqual(
            Desc(size="big", kind="cube").render_bare_plural(), "big cubes"
        )

    def test_nested_relation_renders(self):
        d = Desc(quant="the", kind="cube", rels=(Rel("on", Desc(quant="the", color="red", kind="cube")),))
        self.assertEqual(d.render(), "the cube on the red cube")


class TestAnswerNormalisation(unittest.TestCase):
    def test_yes_and_no_variants(self):
        for spelling in ("yes", "YES", "yes.", "y", "true", "1"):
            self.assertTrue(answers.matches(spelling, Answer("bool", True)), spelling)
        for spelling in ("no", "No!", "n", "false", "0"):
            self.assertTrue(answers.matches(spelling, Answer("bool", False)), spelling)
        self.assertFalse(answers.matches("yes", Answer("bool", False)))
        self.assertFalse(answers.matches("no", Answer("bool", True)))

    def test_numbers_words_and_digits(self):
        self.assertTrue(answers.matches("2", Answer("count", 2)))
        self.assertTrue(answers.matches("two", Answer("count", 2)))
        self.assertFalse(answers.matches("3", Answer("count", 2)))

    def test_synonyms(self):
        self.assertTrue(answers.matches("large", Answer("value", "big")))
        self.assertTrue(answers.matches("little", Answer("value", "small")))
        self.assertTrue(answers.matches("gray", Answer("value", "grey")))
        self.assertTrue(answers.matches("block", Answer("value", "cube")))

    def test_numbers_are_not_read_as_booleans(self):
        """0 and 1 belong to both vocabularies; the question decides which.

        Regression: a context-free reading graded a count of 1 as "yes", so the
        testee was marked wrong on questions it had answered right.
        """
        self.assertTrue(answers.matches("1", Answer("count", 1)))
        self.assertTrue(answers.matches("0", Answer("count", 0)))
        self.assertTrue(answers.matches("1", Answer("bool", True)))
        self.assertTrue(answers.matches("0", Answer("bool", False)))
        self.assertFalse(answers.matches("0", Answer("count", 1)))
        self.assertFalse(answers.matches("1", Answer("bool", False)))
        # a number can never name an attribute
        self.assertFalse(answers.matches("1", Answer("value", "blue")))
        self.assertFalse(answers.matches("0", Answer("value", "red")))

    def test_non_answers_count_as_wrong(self):
        for spelling in ("", "   ", None, "I don't know", "maybe", "possibly",
                         "the red one", "blue cube"):
            self.assertFalse(answers.matches(spelling, Answer("value", "blue")), repr(spelling))

    def test_protocol_requires_the_closed_form(self):
        # A chatty sentence is not the closed form P0 asks for.
        self.assertFalse(answers.matches("It is blue", Answer("value", "blue")))
        self.assertFalse(answers.matches("Yes, it is", Answer("bool", True)))
        # ...but case and trailing punctuation are forgiven.
        self.assertTrue(answers.matches("  Blue.  ", Answer("value", "blue")))


if __name__ == "__main__":
    unittest.main()
