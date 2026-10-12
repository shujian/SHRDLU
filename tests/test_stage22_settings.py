"""Stage 22 acceptance: the settings file (``shrdlu.ini``).

Stage 21 left seven programs with 52 options.  Almost every run wants the same
handful of values, so they moved into one commented file with the defaults
written out; a command line now only says what *this* run does differently.

What has to hold:

* the shipped file is exactly what the writer produces, so it cannot drift from
  the built-in defaults (a test compares the two);
* a value in the file is used, and a command-line flag still wins over it;
* the shared section reaches every program, a program's own section wins over
  it, and a key a program declares is owned outright — ``shrdlu-exam`` writes
  ten questions even when the shared section says zero;
* a broken file is reported, not ignored.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)  # project root
sys.path.insert(0, HERE)  # tests dir

from shrdlu import settings  # noqa: E402
from shrdlu.env import generator  # noqa: E402
from shrdlu.env.cli import env_main, exam_main, render_main, scene_main  # noqa: E402
from shrdlu.testee.cli import testee_main  # noqa: E402

CONFIG = os.path.join(ROOT, settings.CONFIG_NAME)


class TestTheShippedFile(unittest.TestCase):
    def test_the_file_is_exactly_what_the_writer_produces(self):
        with open(CONFIG, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), settings.default_text())

    def test_the_shapes_default_is_the_generator_s_one(self):
        cfg = settings.load("env", path=CONFIG)
        self.assertEqual(cfg["shapes"], ",".join(generator.SHAPES))

    def test_every_program_loads_it(self):
        for program in sorted(settings.PROGRAM_KEYS):
            with self.subTest(program=program):
                cfg = settings.load(program, path=CONFIG)
                self.assertEqual(cfg.source, CONFIG)

    def test_writing_refuses_to_overwrite_unless_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.ini")
            settings.write_default(path)
            with self.assertRaises(settings.SettingsError):
                settings.write_default(path)
            settings.write_default(path, force=True)


class TestReading(unittest.TestCase):
    def write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".ini", delete=False,
                                             encoding="utf-8")
        handle.write(text)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_a_file_overrides_the_built_in_default(self):
        path = self.write("[shrdlu]\ntestee = example\n")
        self.assertEqual(settings.load("env", path=path)["testee"], "example")

    def test_the_shared_section_reaches_every_program(self):
        path = self.write("[shrdlu]\nobserve = image\n")
        for program in ("env", "play", "report"):
            with self.subTest(program=program):
                self.assertEqual(settings.load(program, path=path)["observe"], "image")

    def test_a_program_section_wins_over_the_shared_one(self):
        path = self.write("[shrdlu]\nquestions = 3\n[shrdlu-exam]\nquestions = 7\n")
        self.assertEqual(settings.load("env", path=path)["questions"], 3)
        self.assertEqual(settings.load("exam", path=path)["questions"], 7)

    def test_a_declared_key_is_owned_by_its_program(self):
        """The shared zero must not turn the exam author into a no-op."""
        path = self.write("[shrdlu]\nquestions = 0\n")
        self.assertEqual(settings.load("exam", path=path)["questions"], 10)

    def test_an_empty_value_means_not_set(self):
        path = self.write("[shrdlu]\nseed =\nrecord =\n")
        cfg = settings.load("env", path=path)
        self.assertIsNone(cfg["seed"])
        self.assertIsNone(cfg["record"])

    def test_booleans_are_read_both_ways(self):
        path = self.write("[shrdlu]\nquiet = yes\n[shrdlu-play]\npause = no\n")
        self.assertTrue(settings.load("env", path=path)["quiet"])
        self.assertFalse(settings.load("play", path=path)["pause"])

    def test_an_unknown_key_in_this_program_s_section_is_reported(self):
        path = self.write("[shrdlu-report]\nnope = 1\n")
        with self.assertRaises(settings.SettingsError) as caught:
            settings.load("report", path=path)
        self.assertIn("nope", str(caught.exception))

    def test_a_value_of_the_wrong_kind_is_reported(self):
        path = self.write("[shrdlu]\ntimeout = soon\n")
        with self.assertRaises(settings.SettingsError) as caught:
            settings.load("env", path=path)
        self.assertIn("timeout", str(caught.exception))

    def test_a_missing_file_that_was_named_is_an_error(self):
        with self.assertRaises(settings.SettingsError):
            settings.load("env", path=os.path.join(ROOT, "no-such.ini"))

    def test_the_environment_variable_names_a_file(self):
        path = self.write("[shrdlu]\ntestee = muted\n")
        with mock.patch.dict(os.environ, {settings.ENV_VAR: path}):
            self.assertEqual(settings.load("env")["testee"], "muted")

    def test_the_file_is_looked_for_upwards(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = os.path.join(tmp, "a", "b")
            os.makedirs(nested)
            settings.write_default(os.path.join(tmp, settings.CONFIG_NAME))
            self.assertEqual(settings.find(start=nested),
                             os.path.join(tmp, settings.CONFIG_NAME))

    def test_with_no_file_anywhere_the_built_ins_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(settings, "PROJECT_ROOT", tmp), \
                    mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(settings.ENV_VAR, None)
                cfg = settings.load("env", start=tmp)
        self.assertEqual(cfg["testee"], "example")
        self.assertIsNone(cfg.source)


class TestTheProgramsUseIt(unittest.TestCase):
    def write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".ini", delete=False,
                                            encoding="utf-8")
        handle.write(text)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def run_env(self, path, argv):
        env = dict(os.environ, **{settings.ENV_VAR: path})
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out):
            code = env_main.main(argv)
        return code, out.getvalue()

    def test_the_file_decides_what_a_bare_run_does(self):
        path = self.write("[shrdlu]\nquestions = 5\ntestee = example\nquiet = yes\n")
        code, text = self.run_env(path, [])
        self.assertEqual(code, 1)                 # 最小示例不理解
        self.assertIn("/5", text)                 # five questions, from the file

    def test_a_flag_still_beats_the_file(self):
        path = self.write("[shrdlu]\nquestions = 5\ntestee = example\nquiet = yes\n")
        code, text = self.run_env(path, ["--testee", "example"])
        self.assertEqual(code, 1)
        self.assertIn("/5", text)

    def test_a_broken_file_stops_the_program(self):
        path = self.write("[shrdlu]\ntimeout = soon\n")
        err = io.StringIO()
        with mock.patch.dict(os.environ, {settings.ENV_VAR: path}), \
                contextlib.redirect_stderr(err):
            code = env_main.main(["--quiet"])
        self.assertEqual(code, 2)
        self.assertIn("timeout", err.getvalue())

    def test_a_broken_file_stops_every_program(self):
        path = self.write("[shrdlu-exam]\nillegal = lots\n")
        err = io.StringIO()
        with mock.patch.dict(os.environ, {settings.ENV_VAR: path}), \
                contextlib.redirect_stderr(err):
            code = exam_main.main(["--check", CONFIG])
        self.assertEqual(code, 2)
        self.assertIn("illegal", err.getvalue())

    def test_a_key_in_the_wrong_section_is_reported(self):
        """``level`` belongs to shrdlu-scene; the shared section must not swallow it."""
        path = self.write("[shrdlu]\nlevel = 2\n")
        with self.assertRaises(settings.SettingsError) as caught:
            settings.load("env", path=path)
        self.assertIn("level", str(caught.exception))

    def test_the_settings_program_reports_where_values_come_from(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = settings.main(["--program", "env"])
        self.assertEqual(code, 0)
        self.assertIn("env:", out.getvalue())
        self.assertIn("scenario", out.getvalue())


class TestTheSplitBetweenFlagsAndTheFile(unittest.TestCase):
    """Command-line options say what *this* run is; standing values live in the file.

    Stage 23 moved the environment-shaped options (``shapes``, ``timeout``,
    ``scale``, ``level``, ``reasoning_ratio``, ``model``, ``ollama_url``) out of
    the command line, so the surface a user has to remember stays small.
    """

    def setUp(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".ini", delete=False,
                                            encoding="utf-8")
        handle.write("[shrdlu]\ntimeout = 3.5\nshapes = attr\n"
                     "[shrdlu-render]\nscale = 1.5\n")
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        self.path = handle.name

    def cfg(self, program):
        return settings.load(program, path=self.path)

    def test_the_standing_options_are_not_flags(self):
        gone = {
            env_main: ("--shapes", "--timeout"),
            render_main: ("--scale",),
            scene_main: ("--level",),
            exam_main: ("--reasoning-ratio",),
            testee_main: ("--model", "--ollama-url"),
        }
        for module, flags in gone.items():
            parser = module.build_parser()
            known = {name for action in parser._actions
                     for name in action.option_strings}
            for flag in flags:
                with self.subTest(program=module.__name__, flag=flag):
                    self.assertNotIn(flag, known)

    def test_the_file_values_reach_the_parsed_arguments(self):
        args = env_main.build_parser(self.cfg("env")).parse_args([])
        self.assertEqual(args.cfg["timeout"], 3.5)
        self.assertEqual(args.cfg["shapes"], "attr")
        drawn = render_main.build_parser(self.cfg("render")).parse_args([])
        self.assertEqual(drawn.cfg["scale"], 1.5)

    def test_the_file_shapes_reach_the_generated_bank(self):
        args = env_main.build_parser(self.cfg("env")).parse_args(
            ["--questions", "4"])
        bank = env_main.load_bank(args)
        self.assertEqual({generator.shape_of(q) for q in bank.questions}, {"attr"})
