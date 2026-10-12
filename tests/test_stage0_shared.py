"""Stage 0 acceptance: the shared library (world + snapshot + ops).

Run with:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # project root
sys.path.insert(0, HERE)                   # tests dir

from support import apply_instructions, load_scenario, scene_world  # noqa: E402

from shrdlu import ops, snapshot  # noqa: E402
from shrdlu.world import World, WorldError, check_consistent  # noqa: E402

#: The first-version scene, from scenarios/first-version.json (协议 §8.1)
SCENARIO = load_scenario()
SAMPLE = SCENARIO["state"]


def sample_world() -> World:
    return scene_world(SCENARIO)


class TestSnapshot(unittest.TestCase):
    def test_sample_is_consistent(self):
        self.assertEqual(check_consistent(sample_world()), [])

    def test_all_three_position_forms_round_trip(self):
        w = sample_world()
        w.set_pos("c", ("hand",))
        first = snapshot.to_snapshot(w)
        self.assertEqual(first["hand"], "c")
        again = snapshot.to_snapshot(snapshot.loads(snapshot.dumps(w)))
        self.assertEqual(first, again)

    def test_round_trip_is_stable(self):
        w = sample_world()
        once = snapshot.to_snapshot(w)
        twice = snapshot.to_snapshot(snapshot.from_snapshot(once))
        self.assertEqual(once, twice)

    def test_dumps_is_valid_json(self):
        text = snapshot.dumps(sample_world())
        self.assertIsInstance(json.loads(text), dict)

    def test_duplicate_id_rejected(self):
        bad = {"objects": [dict(SAMPLE["objects"][0]), dict(SAMPLE["objects"][0])]}
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.from_snapshot(bad)

    def test_unresolvable_placement_rejected(self):
        bad = {"objects": [
            {"id": "a", "kind": "cube", "color": "red", "size": "big",
             "pos": ["on", "missing"]},
        ]}
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.from_snapshot(bad)

    def test_stack_uses_support_height(self):
        w = sample_world()
        # a genuine two-high stack: red <- green <- blue
        w.set_pos("c", ("on", "a"))
        self.assertEqual(w.pos_of("c"), ("on", "a"))
        self.assertEqual(w.height("b"), 2)
        self.assertEqual(w.height("a"), 1)
        self.assertEqual(check_consistent(w), [])


class TestWorldMutationAtomicity(unittest.TestCase):
    def test_add_unknown_support_does_not_leave_object(self):
        w = sample_world()
        with self.assertRaises(WorldError):
            w.add("cube", "red", "small", on="missing", ident="new")
        self.assertIsNone(w.get("new"))

    def test_set_pos_invalid_target_does_not_release_hand(self):
        w = sample_world()
        w.set_pos("c", ("hand",))
        with self.assertRaises(WorldError):
            w.set_pos("c", ("on", "missing"))
        self.assertEqual(w.hand, "c")
        self.assertEqual(w.pos_of("c"), ("hand",))

    def test_set_pos_rejects_empty_position_as_world_error(self):
        with self.assertRaises(WorldError):
            sample_world().set_pos("a", ())


class TestPredicates(unittest.TestCase):
    def setUp(self):
        self.w = sample_world()

    def test_on_and_supported(self):
        self.assertTrue(self.w.is_on("a", "b"))
        self.assertTrue(self.w.is_supported("a"))
        self.assertFalse(self.w.is_supported("b"))

    def test_clear(self):
        self.assertTrue(self.w.is_clear("a"))
        self.assertFalse(self.w.is_clear("b"))
        self.assertTrue(self.w.is_clear("c"))
        self.assertTrue(self.w.is_clear("e"))

    def test_pyramid_is_always_clear_but_never_supports(self):
        self.assertTrue(self.w.is_clear("d"))
        self.assertFalse(self.w.get("d").supports_things)

    def test_an_unknown_position_form_is_refused(self):
        """There is no containment any more, so ``in`` is not a position."""
        with self.assertRaises(WorldError):
            self.w.set_pos("a", ("in", "e"))


class TestLoadingRefusesImpossibleStates(unittest.TestCase):
    """A snapshot is input; a world that cannot exist must not come out of it.

    Existence is checked as each placement is applied, but nothing checked that
    the result made sense *together* — and a cycle of supports is expressible,
    so it used to be loaded happily and then look like a position.  Bad input
    should fail here, where the input is, and not far away and strangely.
    """

    def _load(self, rows, hand=None):
        return snapshot.from_snapshot({"objects": rows, "hand": hand})

    def _row(self, ident, pos):
        return {"id": ident, "kind": "cube", "color": "red", "size": "big", "pos": pos}

    def test_a_cycle_of_supports_is_refused(self):
        with self.assertRaises(snapshot.SnapshotError) as caught:
            self._load([self._row("a", ["on", "b"]), self._row("b", ["on", "a"])])
        self.assertIn("cycle", str(caught.exception))

    def test_resting_on_something_that_cannot_support_is_refused(self):
        rows = [self._row("a", ["on", "b"]),
                {"id": "b", "kind": "pyramid", "color": "blue", "size": "big",
                 "pos": ["table"]}]
        with self.assertRaises(snapshot.SnapshotError) as caught:
            self._load(rows)
        self.assertIn("cannot support", str(caught.exception))

    def test_an_object_resting_on_itself_is_refused(self):
        with self.assertRaises(snapshot.SnapshotError):
            self._load([self._row("a", ["on", "a"])])

    def test_a_hand_holding_nothing_is_refused(self):
        with self.assertRaises(snapshot.SnapshotError):
            self._load([self._row("a", ["table"])], hand="ghost")

    def test_a_sound_state_still_loads(self):
        world = self._load([self._row("a", ["table"]), self._row("b", ["on", "a"])])
        self.assertEqual(world.pos_of("b"), ("on", "a"))


class TestOperations(unittest.TestCase):
    def setUp(self):
        self.w = sample_world()

    def legal(self, op, *args):
        return ops.check(self.w, op, list(args)).legal

    def reason(self, op, *args):
        return ops.check(self.w, op, list(args)).reason

    # -- the §8.2 sample sequence -----------------------------------------
    def test_sample_sequence(self):
        self.assertTrue(self.legal("pick_up", "d"))
        ops.apply(self.w, "put_on", ["d", "c"])

        # step 3: illegal, because the red cube is not clear
        self.assertFalse(self.legal("pick_up", "b"))
        self.assertIn("not clear", self.reason("pick_up", "b"))

        # step 4: legal via implicit pickup
        self.assertTrue(self.legal("put_on", "e", "a"))
        ops.apply(self.w, "put_on", ["e", "a"])

        # resulting truth, as recorded in the protocol
        self.assertEqual(self.w.pos_of("e"), ("on", "a"))
        self.assertEqual(self.w.pos_of("d"), ("on", "c"))
        self.assertEqual(self.w.pos_of("b"), ("table",))
        self.assertIsNone(self.w.hand)
        self.assertEqual(check_consistent(self.w), [])

    # -- legality boundaries ----------------------------------------------
    def test_hand_can_hold_only_one(self):
        ops.apply(self.w, "pick_up", ["c"])
        self.assertFalse(self.legal("pick_up", "e"))
        self.assertIn("hand is not empty", self.reason("pick_up", "e"))

    def test_pyramid_cannot_support(self):
        self.assertFalse(self.legal("put_on", "b", "d"))
        self.assertIn("cannot support", self.reason("put_on", "b", "d"))

    def test_cannot_put_object_on_itself(self):
        self.assertFalse(self.legal("put_on", "b", "b"))

    def test_put_in_is_not_an_operation_at_all(self):
        self.assertNotIn("put_in", ops.OPERATIONS)
        self.assertFalse(self.legal("put_in", "b", "c"))
        self.assertIn("unknown operation", self.reason("put_in", "b", "c"))

    def test_cannot_pick_up_a_fixed_object(self):
        self.assertFalse(self.legal("pick_up", "table"))

    def test_unknown_operation_and_arity(self):
        self.assertFalse(self.legal("levitate", "b"))
        self.assertFalse(self.legal("put_on", "b"))

    def test_apply_raises_on_illegal(self):
        with self.assertRaises(ops.IllegalAction):
            ops.apply(self.w, "pick_up", ["b"])

    def test_put_on_not_clear_target_is_illegal(self):
        # make c occupied, then trying to stack on it must fail
        self.assertTrue(self.legal("put_on", "d", "c"))
        ops.apply(self.w, "put_on", ["d", "c"])
        self.assertFalse(self.w.is_clear("c"))
        self.assertFalse(self.legal("put_on", "a", "c"))
        self.assertIn("not clear", self.reason("put_on", "a", "c"))

    def test_idempotent_put_on(self):
        # putting x on y when it is already there is allowed
        self.assertTrue(self.legal("put_on", "a", "b"))


class TestScenarioData(unittest.TestCase):
    """The scenario file is the single source of truth for the sample scene."""

    def test_instruction_sequence_matches_recorded_legality(self):
        world = scene_world(SCENARIO)
        for step in SCENARIO["instructions"]:
            verdict = ops.check(world, step["op"], list(step["args"]))
            with self.subTest(step=step["op"], args=step["args"]):
                self.assertEqual(verdict.legal, step["legal"])
                if "reason_contains" in step:
                    self.assertIn(step["reason_contains"], verdict.reason or "")
                if verdict.legal:
                    ops.apply(world, step["op"], list(step["args"]))

    def test_final_state_matches_the_recorded_expectation(self):
        world = scene_world(SCENARIO)
        apply_instructions(world, SCENARIO["instructions"])
        expected = snapshot.from_snapshot(SCENARIO["expected_final_state"])
        self.assertEqual(snapshot.to_snapshot(world), snapshot.to_snapshot(expected))
        self.assertEqual(check_consistent(world), [])


class TestConsistencyDetector(unittest.TestCase):
    def test_detects_a_cycle_of_supports(self):
        """Pointers can be written in a loop; nothing else can go wrong this way.

        The old representation made a loop impossible — an object's height came
        from its cell — and made "floating" possible instead.  Now it is the
        other way round, and the loop is what has to be caught.
        """
        w = sample_world()
        w.get("a").support = "c"      # a rests on b, b on the table
        w.get("c").support = "a"
        self.assertTrue(check_consistent(w))

    def test_detects_resting_on_an_unknown_object(self):
        w = sample_world()
        w.get("c").support = "ghost"
        self.assertTrue(check_consistent(w))

    def test_detects_held_mismatch(self):
        w = sample_world()
        w.get("c").held = True  # but world.hand stays None
        self.assertTrue(check_consistent(w))


if __name__ == "__main__":
    unittest.main()
