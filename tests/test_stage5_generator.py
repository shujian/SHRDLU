"""Stage 5 acceptance: the question generator.

Acceptance for this stage, from docs/develop/开发进度.md:

* a fixed seed reproduces the same bank;
* no generated question hits an ambiguous definite description;
* and — added here — no generated question has two possible readings, because
  the generator uses the parser as a grammar oracle and drops the ambiguous
  ones rather than asking a question that could be graded either way.
"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # project root
sys.path.insert(0, HERE)                   # tests dir

from shrdlu import questions  # noqa: E402
from shrdlu.env import generator, host, scenario  # noqa: E402
from shrdlu.testee import nlp  # noqa: E402

SHAPES = generator.SHAPES

#: Enumerating the pool parses every candidate, so build the world once.
_WORLD = None


def world():
    global _WORLD
    if _WORLD is None:
        _WORLD = scenario.load("first-version").final_world()
    return _WORLD


class TestValidity(unittest.TestCase):
    def test_every_generated_question_is_valid(self):
        pool = generator.candidates(world())
        self.assertTrue(pool)
        for question in pool:
            with self.subTest(question=questions.render(question)):
                self.assertIsNone(questions.validate(question, world()))

    def test_no_generated_question_has_an_ambiguous_description(self):
        """The specific failure mode the protocol calls out in §2.1."""
        bad = []
        for question in generator.candidates(world()):
            text = questions.render(question)
            try:
                questions.validate(question, world())
            except Exception as exc:  # pragma: no cover - defensive
                bad.append((text, exc))
        self.assertEqual(bad, [])

    def test_every_generated_question_has_exactly_one_reading(self):
        for question in generator.candidates(world()):
            text = questions.render(question)
            with self.subTest(question=text):
                self.assertEqual(nlp.parse_question(text), question)

    def test_no_duplicates_in_the_pool(self):
        pool = generator.candidates(world())
        self.assertEqual(len(pool), len(set(pool)))


class TestDeterminism(unittest.TestCase):
    def test_the_same_seed_gives_the_same_bank(self):
        a = generator.generate(world(), count=12, seed=7)
        b = generator.generate(world(), count=12, seed=7)
        self.assertEqual(a, b)

    def test_different_seeds_give_different_banks(self):
        a = generator.generate(world(), count=12, seed=7)
        b = generator.generate(world(), count=12, seed=8)
        self.assertNotEqual(a, b)

    def test_a_bank_has_no_repeats(self):
        bank = generator.generate(world(), count=20, seed=5)
        self.assertEqual(len(bank), len(set(bank)))

    def test_asking_for_more_than_exists_is_capped_not_fatal(self):
        total = len(generator.candidates(world()))
        bank = generator.generate(world(), count=total + 500, seed=1)
        self.assertLessEqual(len(bank), total)
        self.assertTrue(bank)


class TestVariety(unittest.TestCase):
    def test_the_pool_covers_every_shape(self):
        report = generator.balance(generator.candidates(world()), world())
        for shape in SHAPES:
            with self.subTest(shape=shape):
                self.assertGreater(report.get("shape:%s" % shape, 0), 0)

    def test_a_bank_mixes_shapes(self):
        bank = generator.generate(world(), count=20, seed=4)
        shapes = {generator.shape_of(q) for q in bank}
        self.assertGreaterEqual(len(shapes), 3, shapes)

    def test_a_bank_mixes_yes_and_no_answers(self):
        """A bank of all-"no" questions would let a always-no testee score well."""
        bank = generator.generate(world(), count=20, seed=4)
        answers = {questions.evaluate(q, world()).text() for q in bank}
        self.assertIn("yes", answers)
        self.assertIn("no", answers)

    def test_shape_filter_is_respected(self):
        bank = generator.generate(world(), count=8, seed=2, shapes=("attr",))
        self.assertTrue(bank)
        self.assertEqual({generator.shape_of(q) for q in bank}, {"attr"})


class TestGeneratedBankPlays(unittest.TestCase):
    """A generated bank must work end to end, not just be well formed."""

    def setUp(self):
        self.sc = generator.scenario_with_bank(scenario.load("first-version"), count=15, seed=13)

    def test_recorded_text_and_answers_match_the_generator(self):
        final = self.sc.final_world()
        for question, text, answer in zip(
            self.sc.questions, self.sc.question_text, self.sc.question_answer
        ):
            with self.subTest(question=text):
                self.assertEqual(questions.render(question), text)
                self.assertEqual(questions.evaluate(question, final).text(), answer)

    def test_generated_bank_is_stable_across_runs(self):
        again = generator.scenario_with_bank(scenario.load("first-version"), count=15, seed=13)
        self.assertEqual(self.sc.question_text, again.question_text)


if __name__ == "__main__":
    unittest.main()
