"""Stage 8 acceptance: authoring — instructions and questions for a scene.

This is the layer that turns a scene into an exam, and it exists because of one
fact established in stage 7: **a scene with no instructions cannot catch a
testee that ignores its own actions.**  Instructions create change; questions
are about the result; and a question is only worth asking in proportion to how
much the instructions matter to its answer.

The headline test is :meth:`TestFrozenTesteeIsNowCaught` — the same variant that
sailed through a question-only match in stage 7 must now fail.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)  # project root
sys.path.insert(0, HERE)  # tests dir

from shrdlu import ops, questions, snapshot  # noqa: E402
from shrdlu.testee.example import ExampleTestee  # noqa: E402
from shrdlu.env import authoring, commands, generator, host, scenario, worldgen  # noqa: E402
from shrdlu.testee import nlp  # noqa: E402
from shrdlu.env.cli import exam_main  # noqa: E402

SEEDS = tuple(range(1, 7))

#: Writing an exam searches over instruction sequences, so build each once.
_EXAMS = {}


def exam_for(seed, spec=None):
    spec = spec or authoring.ExamSpec()
    key = (seed, json.dumps(spec.as_json(), sort_keys=True))
    if key not in _EXAMS:
        scene = worldgen.generate(worldgen.Spec(), seed=seed)
        _EXAMS[key] = authoring.author(scene.state, scene.name, spec=spec, seed=seed)
    return _EXAMS[key]


def authored(seeds=SEEDS, spec=None):
    for seed in seeds:
        yield seed, exam_for(seed, spec)


class TestInstructions(unittest.TestCase):
    def test_the_same_seed_gives_the_same_exam(self):
        _, first_exam = exam_for(3)
        scene = worldgen.generate(worldgen.Spec(), seed=3)
        _, again_exam = authoring.author(scene.state, scene.name, seed=3)
        self.assertEqual([i.text for i in first_exam.instructions],
                         [i.text for i in again_exam.instructions])
        self.assertEqual([questions.render(q) for q in first_exam.questions],
                         [questions.render(q) for q in again_exam.questions])

    def test_the_step_count_is_within_the_spec(self):
        spec = authoring.ExamSpec()
        for seed, (_, exam) in authored(spec=spec):
            with self.subTest(seed=seed):
                self.assertGreaterEqual(len(exam.instructions), spec.min_steps)
                self.assertLessEqual(len(exam.instructions), spec.max_steps)

    def test_the_recorded_legality_is_the_real_legality(self):
        for seed, (written, exam) in authored():
            world = written.world()
            for step in written.instructions:
                with self.subTest(seed=seed, text=step.text):
                    verdict = ops.check(world, step.op, list(step.args))
                    self.assertEqual(verdict.legal, step.legal)
                    if verdict.legal:
                        ops.apply(world, step.op, list(step.args))

    def test_there_is_exactly_one_trap_by_default(self):
        spec = authoring.ExamSpec()
        for seed, (_, exam) in authored(spec=spec):
            illegal = [i for i in exam.instructions if not i.legal]
            with self.subTest(seed=seed):
                self.assertEqual(len(illegal), spec.illegal_steps)

    def test_a_trap_records_why_it_is_impossible(self):
        for seed, (written, _) in authored():
            world = written.world()
            for step in written.instructions:
                if step.legal:
                    ops.apply(world, step.op, list(step.args))
                    continue
                with self.subTest(seed=seed, text=step.text):
                    self.assertTrue(step.reason_contains)
                    verdict = ops.check(world, step.op, list(step.args))
                    self.assertIn(step.reason_contains, verdict.reason or "")

    def test_a_trap_is_not_the_first_instruction(self):
        """There has to be something to have tracked before the trap lands."""
        for seed, (written, _) in authored():
            with self.subTest(seed=seed):
                self.assertTrue(written.instructions[0].legal)

    def test_the_instructions_actually_change_the_world(self):
        for seed, (written, _) in authored():
            initial = snapshot.to_snapshot(written.world())
            final = snapshot.to_snapshot(written.final_world())
            with self.subTest(seed=seed):
                self.assertNotEqual(initial, final)

    def test_the_recorded_text_is_what_the_env_will_send(self):
        """The recorded wording must survive the match unchanged."""
        written, _ = exam_for(3)
        result = host.run(written, ExampleTestee())
        sent = [s.sent for s in result.steps if s.kind == "command"]
        self.assertEqual(sent, [i.text for i in written.instructions])


class TestBank(unittest.TestCase):
    def test_the_reasoning_quota_is_met(self):
        spec = authoring.ExamSpec()
        for seed, (written, exam) in authored(spec=spec):
            initial, final = written.world(), written.final_world()
            reasoning = sum(1 for q in written.questions
                            if authoring.is_discriminating(q, initial, final))
            with self.subTest(seed=seed):
                self.assertGreaterEqual(reasoning / len(written.questions),
                                        spec.min_reasoning_ratio - 1e-9)

    def test_the_bank_size_is_honoured(self):
        spec = authoring.ExamSpec(questions=8)
        for seed, (written, _) in authored(spec=spec):
            with self.subTest(seed=seed):
                self.assertEqual(len(written.questions), 8)

    def test_every_question_is_valid_against_the_final_state(self):
        for seed, (written, _) in authored():
            final = written.final_world()
            for question in written.questions:
                with self.subTest(seed=seed, text=questions.render(question)):
                    self.assertIsNone(questions.validate(question, final))

    def test_every_question_has_exactly_one_reading(self):
        for seed, (written, _) in authored():
            for question in written.questions:
                text = questions.render(question)
                with self.subTest(seed=seed, text=text):
                    self.assertEqual(nlp.parse_question(text), question)

    def test_no_duplicate_questions(self):
        for seed, (written, _) in authored():
            with self.subTest(seed=seed):
                self.assertEqual(len(written.questions), len(set(written.questions)))

    def test_recorded_text_and_answers_match_the_machinery(self):
        for seed, (written, _) in authored():
            final = written.final_world()
            for question, text, answer in zip(written.questions,
                                              written.question_text,
                                              written.question_answer):
                with self.subTest(seed=seed, text=text):
                    self.assertEqual(questions.render(question), text)
                    self.assertEqual(questions.evaluate(question, final).text(), answer)

    def test_a_reasoning_question_really_does_depend_on_the_instructions(self):
        """The quota must be real, not just an assertion about the pool."""
        for seed, (written, _) in authored():
            initial, final = written.world(), written.final_world()
            for question in written.questions:
                if not authoring.is_discriminating(question, initial, final):
                    continue
                try:
                    before = questions.evaluate(question, initial).text()
                except questions.QuestionError:
                    continue  # cannot even be asked of the initial state
                with self.subTest(seed=seed, text=questions.render(question)):
                    self.assertNotEqual(before, questions.evaluate(question, final).text())


class TestFrozenTesteeIsNowCaught(unittest.TestCase):
    """The point of the whole layer.

    Stage 7 established that a frozen testee passes a question-only match,
    because initial and final states are identical.  With a generated exam they
    must no longer get away with it.
    """


class TestValidation(unittest.TestCase):
    def test_a_freshly_written_exam_is_sound(self):
        for seed, (written, _) in authored():
            with self.subTest(seed=seed):
                self.assertEqual(authoring.exam_problems(written), [])

    def test_a_tampered_answer_is_caught(self):
        written, _ = exam_for(3)
        written.question_answer[0] = "definitely-not-the-answer"
        problems = authoring.exam_problems(written)
        self.assertTrue(any("recorded" in p for p in problems), problems)

    def test_a_tampered_legality_flag_is_caught(self):
        written, _ = exam_for(3)
        for step in written.instructions:
            if not step.legal:
                step.legal = True
                break
        self.assertTrue(any("records it as" in p for p in authoring.exam_problems(written)))

    def test_tampered_wording_is_caught(self):
        written, _ = exam_for(3)
        written.instructions[0].text = "Fling the cube into the sun."
        self.assertTrue(any("text mismatch" in p for p in authoring.exam_problems(written)))

    def test_a_weak_bank_is_caught(self):
        written, _ = exam_for(3)
        initial, final = written.world(), written.final_world()
        keep = [q for q in written.questions
                if not authoring.is_discriminating(q, initial, final)]
        written.questions = keep
        written.question_text = [questions.render(q) for q in keep]
        written.question_answer = [questions.evaluate(q, final).text() for q in keep]
        problems = authoring.exam_problems(written)
        self.assertTrue(any("needs reasoning" in p for p in problems), problems)


class TestSerialisationRoundTrip(unittest.TestCase):
    def test_a_written_exam_survives_a_file_round_trip(self):
        written, _ = exam_for(3)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "exam.json")
            scenario.save(written, path)
            loaded = scenario.load(path)
        self.assertEqual(scenario.to_json(loaded), scenario.to_json(written))
        self.assertEqual([i.text for i in loaded.instructions],
                         [i.text for i in written.instructions])
        self.assertEqual(loaded.question_text, written.question_text)
        self.assertEqual(loaded.generated["exam"]["reasoning_pool"],
                         written.generated["exam"]["reasoning_pool"])

    def test_a_reloaded_exam_is_still_playable(self):
        written, _ = exam_for(3)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "exam.json")
            scenario.save(written, path)
            loaded = scenario.load(path)
        result = host.run(loaded, ExampleTestee())
        sent = [s.sent for s in result.steps if s.kind == "command"]
        self.assertEqual(sent, [i.text for i in loaded.instructions])
        self.assertEqual(authoring.exam_problems(loaded), [])


class TestExamCli(unittest.TestCase):
    def test_writing_an_exam_to_a_file(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "exam.json")
            with contextlib.redirect_stdout(io.StringIO()):
                code = exam_main.main(["--seed", "2", "--out", path, "--quiet"])
            self.assertEqual(code, 0)
            loaded = scenario.load(path)
        self.assertTrue(loaded.instructions)
        self.assertEqual(len(loaded.questions), 10)
        self.assertEqual(authoring.exam_problems(loaded), [])

    def test_check_accepts_and_rejects(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "exam.json")
            with contextlib.redirect_stdout(io.StringIO()):
                exam_main.main(["--seed", "2", "--out", path, "--quiet"])

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(exam_main.main(["--check", path]), 0)
            self.assertIn("ok", out.getvalue())

            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            data["questions"][0]["answer"] = "nonsense"
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(exam_main.main(["--check", path]), 1)
            self.assertIn("NOT SOUND", out.getvalue())

    def test_writing_an_exam_for_an_existing_scene(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = os.path.join(tmp, "scene.json")
            worldgen.save(worldgen.generate(worldgen.Spec(), seed=4), scene_path)
            exam_path = os.path.join(tmp, "exam.json")
            with contextlib.redirect_stdout(io.StringIO()):
                code = exam_main.main(["--scene", scene_path, "--seed", "1",
                                       "--out", exam_path, "--quiet"])
            self.assertEqual(code, 0)
            loaded = scenario.load(exam_path)
            scene_objects = len(scenario.load(scene_path).state["objects"])  # type: ignore[arg-type]
        self.assertEqual(len(loaded.state["objects"]), scene_objects)  # type: ignore[arg-type]
        self.assertTrue(loaded.instructions)

    def test_an_impossible_request_fails_cleanly(self):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = exam_main.main(["--illegal", "9", "--steps", "2", "--quiet"])
        self.assertEqual(code, 1)
        self.assertIn("error", err.getvalue())


if __name__ == "__main__":
    unittest.main()
