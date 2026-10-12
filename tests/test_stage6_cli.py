"""Stage 6 acceptance: two independent programs, talking in text.

Everything up to now ran the testee in-process.  This stage is what proves the
protocol is real: the env launches the testee with :mod:`subprocess`, and the
only thing crossing the boundary is JSON lines.

    python3 -m shrdlu.env.cli.env_main --scenario first-version
    python3 -m shrdlu.env.cli.env_main --questions 15 --seed 13 --testee-impl mute
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)  # project root
sys.path.insert(0, HERE)  # tests dir

from shrdlu import protocol, transport  # noqa: E402
from shrdlu.testee.example import ExampleTestee  # noqa: E402
from shrdlu.env import host, scenario  # noqa: E402
from shrdlu.env.cli import env_main  # noqa: E402
from shrdlu.testee.cli import testee_main  # noqa: E402


def launch(impl: str = "example", timeout: float = 15.0) -> transport.SubprocessTestee:
    return transport.SubprocessTestee(env_main.default_testee_command(impl),
                                     timeout=timeout, cwd=ROOT)


class TestSubprocessMatch(unittest.TestCase):
    def test_the_example_testee_runs_in_its_own_process(self):
        player = launch()
        try:
            result = host.run(scenario.load("first-version"), player)
        finally:
            player.close()
        # 最小示例对一切问题答 no、对一切指令拒绝，所以判定必然是不理解，
        # 但整条链路（观察、两轮问句、四条指令）都跑完了
        self.assertEqual(result.verdict, "not_understood", result.render())
        # 两轮问句 + 四条指令都走完了；不需要理解也会走到这里
        self.assertEqual(len(result.steps), 10 + 4 + 10)
        self.assertEqual(len(result.stages), 3)
        self.assertEqual(sorted(result.stages), ["final", "initial", "operations"])

    def test_only_text_crosses_the_boundary(self):
        player = launch()
        try:
            host.run(scenario.load("first-version"), player)
        finally:
            player.close()
        self.assertTrue(player.exchanges)
        for message in player.exchanges:
            self.assertIsInstance(message, str)
            self.assertEqual(protocol.decode(message)["type"] in
                             ("observe", "command", "question"), True)

    def test_observe_gets_no_reply(self):
        """The fire-and-forget convention must hold over a real pipe."""
        player = launch()
        try:
            reply = player.handle(protocol.observe(scenario.load("first-version").state))
        finally:
            player.close()
        self.assertEqual(reply, "")


class TestTransportRobustness(unittest.TestCase):
    def test_a_silent_testee_times_out_instead_of_hanging(self):
        player = transport.SubprocessTestee(
            [sys.executable, "-c", "import sys,time; sys.stdin.readline(); time.sleep(30)"],
            timeout=0.5,
        )
        try:
            with self.assertRaises(transport.TesteeTimeout):
                player.handle(protocol.question("Is the cube clear?"))
        finally:
            player.close(timeout=1.0)

    def test_a_testee_that_exits_immediately_is_reported(self):
        player = transport.SubprocessTestee([sys.executable, "-c", "pass"], timeout=5.0)
        try:
            with self.assertRaises(transport.TransportError):
                player.handle(protocol.question("Is the cube clear?"))
        finally:
            player.close(timeout=1.0)

    def test_a_command_that_does_not_exist_is_reported(self):
        with self.assertRaises(transport.TransportError):
            transport.SubprocessTestee(["definitely-not-a-real-command-12345"])


class TestTransportLimits(unittest.TestCase):
    def test_stderr_is_drained_while_testee_runs(self):
        code = ("import sys; sys.stdin.readline(); "
                "sys.stderr.write('x' * 2000000); sys.stderr.flush(); "
                "sys.stdout.buffer.write(b'ok\\n'); sys.stdout.flush()")
        player = transport.SubprocessTestee([sys.executable, "-c", code], timeout=2.0)
        try:
            reply = player.handle(protocol.question("Is the cube clear?"))
        finally:
            player.close(timeout=1.0)
        self.assertEqual(reply, "ok")

    def test_partial_output_cannot_extend_timeout(self):
        code = ("import sys,time; sys.stdin.readline(); "
                "sys.stdout.write('x'); sys.stdout.flush(); time.sleep(1)")
        player = transport.SubprocessTestee([sys.executable, "-c", code], timeout=0.2)
        try:
            with self.assertRaises(transport.TesteeTimeout):
                player.handle(protocol.question("Is the cube clear?"))
        finally:
            player.close(timeout=1.0)


class TestServeLoop(unittest.TestCase):
    """The testee-side loop, exercised without a process."""

    def run_serve(self, lines):
        stdin = io.BytesIO(b"".join(l.encode() + b"\n" for l in lines))
        stdout = io.BytesIO()
        code = transport.serve(ExampleTestee(), stdin=stdin, stdout=stdout)
        return code, [json.loads(l) for l in stdout.getvalue().decode().splitlines()]

    def test_a_whole_match_can_be_served(self):
        state = json.dumps(scenario.load("first-version").state)
        code, replies = self.run_serve([
            protocol.observe(json.loads(state)),
            protocol.command("Pick up the blue pyramid."),
            protocol.question("Is the blue pyramid on the blue cube?"),
        ])
        self.assertEqual(code, 0)
        # observe produces no reply, so exactly two replies come back
        self.assertEqual(len(replies), 2)
        self.assertEqual(replies[0]["type"], "refuse")
        self.assertEqual(replies[1], {"type": "answer", "text": "no"})

    def test_a_malformed_line_gets_a_refusal_not_a_crash(self):
        code, replies = self.run_serve([
            protocol.observe({"objects": [], "hand": None}),
            "this is not json",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(replies[-1]["type"], "refuse")

    def test_end_of_input_ends_the_loop(self):
        code, replies = self.run_serve([])
        self.assertEqual(code, 0)
        self.assertEqual(replies, [])


class TestEnvCli(unittest.TestCase):
    def test_quiet_run_reports_the_summary(self):
        argv = ["--scenario", "first-version", "--quiet",
                "--testee", "%s -m shrdlu.testee.cli.testee_main" % sys.executable]
        import contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = env_main.main(argv)
        self.assertEqual(code, 1)                 # 最小示例不理解
        self.assertIn("verdict=not_understood", out.getvalue())

    def test_record_is_written_as_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run.json")
            argv = ["--scenario", "first-version", "--quiet", "--record", path,
                    "--testee", "%s -m shrdlu.testee.cli.testee_main" % sys.executable]
            import contextlib
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = env_main.main(argv)
            self.assertEqual(code, 1)
            with open(path, encoding="utf-8") as handle:
                record = json.load(handle)
        self.assertEqual(record["verdict"], "not_understood")
        self.assertEqual(record["asked"], 20)
        # 4 instructions + the bank asked in both question stages
        self.assertEqual(len(record["steps"]), 24)
        self.assertEqual(sorted(record["stages"]),
                         ["final", "initial", "operations"])
        self.assertNotEqual(record["second_state"], record["final_state"])

    def test_a_bad_scenario_exits_with_two(self):
        import contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = env_main.main(["--scenario", "no-such-scenario", "--quiet"])
        self.assertEqual(code, 2)
        self.assertIn("no such scenario", err.getvalue())

    def test_not_understood_exits_with_one(self):
        argv = ["--scenario", "first-version", "--quiet", "--testee", "example"]
        import contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = env_main.main(argv)
        self.assertEqual(code, 1)
        self.assertIn("verdict=not_understood", out.getvalue())

    def test_a_built_in_name_selects_that_implementation(self):
        import contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = env_main.main(["--scenario", "first-version", "--quiet",
                                  "--testee", "example"])
        self.assertEqual(code, 1)
        self.assertIn("verdict=not_understood", out.getvalue())

    def test_a_seed_alone_makes_a_whole_exam(self):
        """No --scenario and no --questions: --seed builds the exam itself."""
        import contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = env_main.main(["--seed", "3", "--quiet", "--testee", "example"])
        self.assertEqual(code, 1)
        self.assertIn("gen-l1-0003", out.getvalue())

    def test_generated_bank_scenario_plays(self):
        argv = ["--questions", "12", "--seed", "13", "--quiet",
                "--testee", "%s -m shrdlu.testee.cli.testee_main" % sys.executable]
        import contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = env_main.main(argv)
        self.assertEqual(code, 1)
        # 生成出来的题库照常走完三段（有些题在第一步问不了，会被跳过）
        self.assertIn("第一步（对初始状态的问句）", out.getvalue())
        self.assertIn("第三步（对变化后状态的问句）", out.getvalue())


class TestTesteeCli(unittest.TestCase):
    def test_list_names_every_implementation(self):
        import contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = testee_main.main(["--list"])
        self.assertEqual(code, 0)
        text = out.getvalue()
        for name in ("example",):
            self.assertIn(name, text)

    def test_unknown_implementation_is_rejected(self):
        with self.assertRaises(SystemExit):
            testee_main.main(["--impl", "nonesuch"])


if __name__ == "__main__":
    unittest.main()
