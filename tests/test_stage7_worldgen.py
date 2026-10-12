"""Stage 7 acceptance: scene generation.

A generated scene has to be *good*, not merely valid.  Three things are checked
here, in rising order of strength:

* it is **physically consistent** — nothing floats, nothing rests on a pyramid,
  nothing big balances on something smaller;
* it is **well formed as a scene** — the right number of objects, colours and
  sizes spread, every object uniquely nameable, and at least one legal
  operation so that instructions can later be generated for it;
* it is **useful as a test** — the questions it supports span several shapes
  and include both ``yes`` and ``no`` answers, and a generated scene can be
  played end to end.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)  # project root
sys.path.insert(0, HERE)  # tests dir

from shrdlu import ops, questions, snapshot  # noqa: E402
from shrdlu.env import generator, host, scenario, worldgen  # noqa: E402
from shrdlu.env.cli import scene_main  # noqa: E402
from shrdlu.world import SUPPORTING_KINDS, check_consistent  # noqa: E402

#: A spread of seeds the guarantees below must hold for.
SEEDS = tuple(range(1, 9))

#: Enumerating a scene's question pool parses every candidate, so both the
#: scenes and their pools are built once and shared between tests.
_SCENES = {}
_POOLS = {}


def scene_for(seed):
    if seed not in _SCENES:
        _SCENES[seed] = worldgen.generate(worldgen.Spec(), seed=seed)
    return _SCENES[seed]


def pool_for(seed):
    if seed not in _POOLS:
        _POOLS[seed] = generator.candidates(scene_for(seed).world())
    return _POOLS[seed]


def scenes(seeds=SEEDS):
    for seed in seeds:
        yield seed, scene_for(seed)


class TestDeterminism(unittest.TestCase):
    def test_the_same_seed_gives_the_same_scene(self):
        first = worldgen.generate(worldgen.Spec(), seed=5)
        second = worldgen.generate(worldgen.Spec(), seed=5)
        self.assertEqual(first.state, second.state)
        self.assertEqual(first.state, scene_for(5).state)

    def test_different_seeds_give_different_scenes(self):
        states = {seed: json.dumps(scene.state, sort_keys=True)
                  for seed, scene in scenes()}
        self.assertGreaterEqual(len(set(states.values())), len(SEEDS) - 2)

    def test_a_scene_records_how_it_was_made(self):
        scene = worldgen.generate(worldgen.Spec(), seed=5)
        self.assertEqual(scene.seed, 5)
        self.assertGreaterEqual(scene.attempts, 1)
        self.assertEqual(scene.as_json()["generated"]["level"], 1)


class TestPhysicalConsistency(unittest.TestCase):
    def test_every_generated_scene_is_consistent(self):
        for seed, scene in scenes():
            with self.subTest(seed=seed):
                self.assertEqual(check_consistent(scene.world()), [])

    def test_nothing_rests_on_a_pyramid(self):
        for seed, scene in scenes():
            world = scene.world()
            for obj in world.actual_objects():
                support = world.support_of(obj)
                if support is None or support.is_fixed:
                    continue
                with self.subTest(seed=seed, obj=obj.ident):
                    self.assertIn(support.kind, SUPPORTING_KINDS)

    def test_nothing_big_balances_on_something_smaller(self):
        rank = worldgen.SIZE_RANK
        for seed, scene in scenes():
            world = scene.world()
            for obj in world.actual_objects():
                support = world.support_of(obj)
                if support is None or support.is_fixed:
                    continue
                with self.subTest(seed=seed, obj=obj.ident):
                    self.assertLessEqual(rank[obj.size], rank[support.size])

    def test_stack_height_stays_within_the_spec(self):
        spec = worldgen.Spec()
        for seed, scene in scenes():
            world = scene.world()
            tallest = max(world.height(o) + 1 for o in world.actual_objects())
            with self.subTest(seed=seed):
                self.assertLessEqual(tallest, spec.max_stack_height)

    def test_no_scene_uses_a_container(self):
        """Level 1 has no containment at all — not in the model, not in a scene."""
        for seed, scene in scenes():
            with self.subTest(seed=seed):
                positions = {o["pos"][0] for o in scene.state["objects"]}
                self.assertEqual(positions - {"table", "on"}, set())

    def test_no_scene_contains_a_box(self):
        for seed, scene in scenes():
            with self.subTest(seed=seed):
                self.assertNotIn("box", {o["kind"] for o in scene.state["objects"]})

    def test_balls_carry_the_shape_vocabulary_boxes_used_to(self):
        """With boxes gone, the third shape has to come from somewhere."""
        kinds = set()
        for seed, scene in scenes():
            kinds |= {o["kind"] for o in scene.state["objects"]}
        self.assertIn("ball", kinds)
        self.assertIn("pyramid", kinds)


class TestSceneQuality(unittest.TestCase):
    def test_every_generated_scene_passes_the_quality_checks(self):
        for seed, scene in scenes():
            with self.subTest(seed=seed):
                self.assertEqual(worldgen.problems(scene.state, scene.spec), [])

    def test_object_count_is_within_the_spec(self):
        spec = worldgen.Spec()
        for seed, scene in scenes():
            count = len(scene.world().actual_objects())
            with self.subTest(seed=seed):
                self.assertGreaterEqual(count, spec.min_objects)
                self.assertLessEqual(count, spec.max_objects)

    def test_colours_and_sizes_are_spread(self):
        spec = worldgen.Spec()
        for seed, scene in scenes():
            objects = scene.world().actual_objects()
            with self.subTest(seed=seed):
                self.assertGreaterEqual(len({o.color for o in objects}),
                                        spec.min_distinct_colors)
                self.assertEqual(len({o.size for o in objects}), 2)

    def test_every_object_is_uniquely_nameable(self):
        for seed, scene in scenes():
            objects = scene.world().actual_objects()
            triples = [(o.color, o.size, o.kind) for o in objects]
            with self.subTest(seed=seed):
                self.assertEqual(len(set(triples)), len(triples))

    def test_shapes_stay_varied(self):
        """No scene should be all cubes: shape questions would be trivial."""
        for seed, scene in scenes():
            kinds = {o.kind for o in scene.world().actual_objects()}
            with self.subTest(seed=seed):
                self.assertGreaterEqual(len(kinds), 2)

    def test_a_legal_operation_always_exists(self):
        """Otherwise the instruction generator would have nothing to work with."""
        for seed, scene in scenes():
            with self.subTest(seed=seed):
                self.assertTrue(ops.legal_operations(scene.world()))


class TestSceneIsATest(unittest.TestCase):
    def test_the_supported_bank_spans_several_shapes(self):
        spec = worldgen.Spec()
        for seed in SEEDS:
            shapes = {generator.shape_of(q) for q in pool_for(seed)}
            with self.subTest(seed=seed):
                self.assertGreaterEqual(len(shapes), spec.min_shapes)

    def test_the_supported_bank_has_both_answers(self):
        for seed in SEEDS:
            world = scene_for(seed).world()
            answers = {questions.evaluate(q, world).text() for q in pool_for(seed)}
            with self.subTest(seed=seed):
                self.assertIn("yes", answers)
                self.assertIn("no", answers)


class TestPersisting(unittest.TestCase):
    def test_saving_and_loading_round_trips(self):
        scene = worldgen.generate(worldgen.Spec(), seed=3)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scene.json")
            worldgen.save(scene, path)
            loaded = scenario.load(path)
        self.assertEqual(loaded.name, scene.name)
        self.assertEqual(loaded.state, scene.state)
        self.assertEqual(loaded.instructions, [])
        self.assertEqual(loaded.questions, [])
        self.assertEqual(loaded.generated["seed"], 3)

    def test_a_saved_scene_is_a_valid_snapshot(self):
        scene = worldgen.generate(worldgen.Spec(), seed=4)
        reread = snapshot.from_snapshot(json.loads(json.dumps(scene.state)))
        self.assertEqual(snapshot.to_snapshot(reread), scene.state)


class TestFailureModes(unittest.TestCase):
    def test_an_unsatisfiable_spec_raises_instead_of_hanging(self):
        contradictory = worldgen.Spec(max_stack_height=1, min_pairs=1, max_attempts=25)
        with self.assertRaises(worldgen.SceneGenerationError):
            worldgen.generate(contradictory, seed=1)

    def test_an_impossible_colour_spread_raises(self):
        impossible = worldgen.Spec(min_distinct_colors=9, max_attempts=25)
        with self.assertRaises(worldgen.SceneGenerationError):
            worldgen.generate(impossible, seed=1)

    def test_problems_reports_what_is_wrong(self):
        bad = {"objects": [
            {"id": "a", "kind": "cube", "color": "red", "size": "big",
             "pos": ["table"]},
        ], "hand": None}
        found = worldgen.problems(bad)
        self.assertTrue(found)
        self.assertTrue(any("object count" in f for f in found), found)

    def test_problems_rejects_an_unreadable_state(self):
        self.assertTrue(worldgen.problems({"objects": []}))


class TestSceneCli(unittest.TestCase):
    def test_generating_one_scene_writes_a_file(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scene.json")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = scene_main.main(["--seed", "2", "--out", path, "--quiet"])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(path))
            loaded = scenario.load(path)
        self.assertEqual(loaded.generated["seed"], 2)

    def test_a_range_of_seeds_is_written_to_a_directory(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = scene_main.main(["--seed", "1-3", "--out-dir", tmp, "--quiet"])
            self.assertEqual(code, 0)
            written = sorted(os.listdir(tmp))
        self.assertEqual(len(written), 3)

    def test_a_comma_list_of_seeds_is_accepted(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                code = scene_main.main(["--seed", "1,4", "--out-dir", tmp, "--quiet"])
            self.assertEqual(code, 0)
            self.assertEqual(len(os.listdir(tmp)), 2)

    def test_check_accepts_a_generated_scene(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scene.json")
            with contextlib.redirect_stdout(io.StringIO()):
                scene_main.main(["--seed", "2", "--out", path, "--quiet"])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = scene_main.main(["--check", path])
        self.assertEqual(code, 0)
        self.assertIn("ok", out.getvalue())

    def test_check_rejects_an_unacceptable_scene(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"name": "bad", "state": {"objects": [
                    {"id": "a", "kind": "cube", "color": "red", "size": "big",
                     "pos": ["table"]},
                ], "hand": None}}, handle)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = scene_main.main(["--check", path])
        self.assertEqual(code, 1)
        self.assertIn("NOT ACCEPTABLE", out.getvalue())

    def test_only_level_one_is_available(self):
        """The level is a standing setting (shrdlu.ini), not a command-line flag."""
        import contextlib
        import io
        from shrdlu import settings
        handle = tempfile.NamedTemporaryFile("w", suffix=".ini", delete=False,
                                            encoding="utf-8")
        handle.write("[shrdlu-scene]\nlevel = 2\n")
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        err = io.StringIO()
        with mock.patch.dict(os.environ, {settings.ENV_VAR: handle.name}), \
                contextlib.redirect_stderr(err):
            code = scene_main.main([])
        self.assertEqual(code, 2)
        self.assertIn("level 1", err.getvalue())


if __name__ == "__main__":
    unittest.main()
