"""Stage 10 acceptance: drawing a scene for a picture-based testee.

The picture is the only thing a vision testee is shown, so it has to carry the
whole state.  That is not something to take on trust, so the central test reads
the drawing back **from its own geometry** and compares with the truth.

Two separate claims are checked:

* **completeness** — ``read_back`` recovers every object and relation.  This is
  fatal if it fails.
* **legibility** — nothing off-canvas, no two labels on top of each other, no
  two objects drawn in the same place.  Also fatal.
* **roominess** — very small shapes, or big and small nearly the same width.
  Advisory only: a crowded scene has to compromise.
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)  # project root
sys.path.insert(0, HERE)  # tests dir

from shrdlu import snapshot, world  # noqa: E402
from shrdlu.env import authoring, render, scenario, worldgen  # noqa: E402
from shrdlu.env.cli import render_main  # noqa: E402

BASE = scenario.load("first-version")


_STATES = None


def many_states():
    """A spread of states, including the awkward ones.

    Built once: writing an exam searches over instruction sequences, so
    rebuilding them for every test would dominate the suite's runtime.
    """
    global _STATES
    if _STATES is None:
        out = [("first-version initial", BASE.world()),
               ("first-version final", BASE.final_world())]
        spec = worldgen.Spec()
        for seed in range(1, 9):
            built, _ = authoring.author(worldgen.generate(spec, seed=seed).state,
                                        "g%d" % seed, seed=seed)
            out.append(("gen%d initial" % seed, built.world()))
            out.append(("gen%d final" % seed, built.final_world()))
        _STATES = out
    return _STATES


class TestUnifiedIdentifiers(unittest.TestCase):
    """One identifier space: the id is drawn, and the id is what a testee says."""

    def test_generated_scene_ids_are_short_and_opaque(self):
        for seed in range(1, 9):
            world = worldgen.generate(worldgen.Spec(), seed=seed).world()
            for obj in world.actual_objects():
                with self.subTest(seed=seed, ident=obj.ident):
                    self.assertEqual(len(obj.ident), 1)
                    self.assertIn(obj.ident, worldgen.LABELS)
                    # must not leak what the object is
                    self.assertNotIn(obj.color, obj.ident)
                    self.assertNotIn(obj.kind, obj.ident)
                    self.assertNotIn(obj.size, obj.ident)

    def test_the_drawn_label_is_the_id_itself(self):
        world = BASE.world()
        drawing = render.plan(world)
        labels = {s.ident for s in drawing.shapes}
        self.assertEqual(labels, {o.ident for o in world.actual_objects()})

    def test_every_id_appears_textually_in_the_svg(self):
        svg = render.to_svg(BASE.world())
        for obj in BASE.world().actual_objects():
            with self.subTest(ident=obj.ident):
                self.assertIn(">%s</text>" % obj.ident, svg)

    def test_omitting_labels_removes_them_all(self):
        svg = render.to_svg(BASE.world(), labels=False)
        for obj in BASE.world().actual_objects():
            self.assertNotIn(">%s</text>" % obj.ident, svg)


class TestCompleteness(unittest.TestCase):
    """The drawing must carry colour, size, shape and relation."""

    def test_the_drawing_reads_back_as_the_truth(self):
        for label, world in many_states():
            with self.subTest(state=label):
                drawing = render.plan(world)
                self.assertEqual(
                    render.relation_key(render.read_back(drawing)),
                    render.relation_key(snapshot.to_snapshot(world)),
                )

    def test_the_reader_output_can_be_loaded_back_into_a_world(self):
        """A reading is only useful if it can become a world the testee can use.

        It names no table cells, and it must not need to: the relations it does
        carry have to survive the trip.  This was broken and nothing noticed,
        because the other tests compare relation keys without ever loading one.
        """
        for label, world in many_states()[:6]:
            reading = render.read_back(render.plan(world))
            with self.subTest(state=label):
                rebuilt = snapshot.from_snapshot(reading)
                self.assertEqual(render.relation_key(snapshot.to_snapshot(rebuilt)),
                                 render.relation_key(snapshot.to_snapshot(world)))

    def test_stacking_is_inferred_not_declared(self):
        """Shapes carry no 'what it rests on' field; geometry alone decides."""
        for shape in render.plan(BASE.world()).shapes:
            self.assertFalse(hasattr(shape, "on"))
            self.assertFalse(hasattr(shape, "support"))

    def test_a_lone_object_is_on_the_table(self):
        world = snapshot.from_snapshot({"objects": [
            {"id": "a", "kind": "cube", "color": "red", "size": "big",
             "pos": ["table"]}], "hand": None})
        back = render.read_back(render.plan(world))
        self.assertEqual(back["objects"][0]["pos"], ["table"])

    def test_a_stack_reads_back_as_stacked(self):
        world = BASE.world()
        world.set_pos("c", ("on", "a"))
        back = render.read_back(render.plan(world))
        positions = {row["id"]: row["pos"] for row in back["objects"]}
        self.assertEqual(positions["a"], ["on", "b"])
        self.assertEqual(positions["c"], ["on", "a"])

    def test_a_held_object_reads_back_as_held(self):
        world = BASE.world()
        world.set_pos("a", ("hand",))
        positions = {r["id"]: r["pos"] for r in render.read_back(render.plan(world))["objects"]}
        self.assertEqual(positions["a"], ["hand"])

class TestLegibility(unittest.TestCase):
    def test_layout_audit_is_clean(self):
        for label, world in many_states():
            drawing = render.plan(world)
            with self.subTest(state=label):
                self.assertEqual(render.audit(drawing), [])

    def test_nothing_is_drawn_off_canvas(self):
        for label, world in many_states():
            drawing = render.plan(world)
            for shape in drawing.shapes:
                with self.subTest(state=label, ident=shape.ident):
                    self.assertGreaterEqual(shape.x, 0)
                    self.assertGreaterEqual(shape.top, 0)
                    self.assertLessEqual(shape.x + shape.width, drawing.width)
                    self.assertLessEqual(shape.bottom, drawing.height)

    def test_labels_never_overlap(self):
        for label, world in many_states():
            drawing = render.plan(world)
            plates = [(s.ident, s.label_x, s.label_y) for s in drawing.shapes]
            for index, (ident_a, ax, ay) in enumerate(plates):
                for ident_b, bx, by in plates[index + 1:]:
                    with self.subTest(state=label, pair=(ident_a, ident_b)):
                        self.assertFalse(
                            ax < bx + render.LABEL_W and bx < ax + render.LABEL_W
                            and ay < by + render.LABEL_H and by < ay + render.LABEL_H
                        )

    def test_a_normal_scene_has_no_warnings(self):
        self.assertEqual(render.size_warnings(render.plan(BASE.world())), [])


class TestThePictureExplainsItself(unittest.TestCase):
    """Odd-looking regions must say what they are, or they read as mistakes."""

    def test_a_held_object_gets_a_named_hand_area(self):
        world = BASE.world()
        world.set_pos("a", ("hand",))
        drawing = render.plan(world)
        self.assertIsNotNone(drawing.hand_pad)
        self.assertEqual(drawing.hand_caption, "in hand")
        self.assertIn("in hand", render.to_svg(world))

    def test_the_named_areas_stay_inside_the_canvas(self):
        for ident, place in (("a", ("hand",)), ("c", ("hand",)), ("d", ("hand",))):
            world = BASE.world()
            world.set_pos(ident, place)
            drawing = render.plan(world)
            for area in (drawing.hand_pad,):
                if not area:
                    continue
                ax, ay, aw, ah = area
                with self.subTest(ident=ident, place=place):
                    self.assertGreaterEqual(ax, 0)
                    self.assertGreaterEqual(ay, 0)
                    self.assertLessEqual(ax + aw, drawing.width)
                    self.assertLessEqual(ay + ah, drawing.height)

class TestLeaderLines(unittest.TestCase):
    """A label's line has to touch the object it names.

    The plate is placed first; the far end of the line is then computed from
    the object's own outline.  Both halves of that used to assume every object
    was a cuboid, which is invisible in the data and glaring in the picture:

    * ``Shape.top`` returned ``roof_y - dep`` — the north vertex of a cuboid's
      top face.  A pyramid has no top face, so its label stopped ``dep``
      pixels above the apex, in mid-air.
    * a side label aimed at a fixed corner of the bounding box.  Beside a
      pyramid that point is outside the object entirely.
    """

    def test_top_is_the_highest_point_that_gets_drawn(self):
        for label, world in many_states():
            for shape in render.plan(world).shapes:
                with self.subTest(state=label, ident=shape.ident):
                    drawn = min(y for poly in render.drawn_body(shape)
                                for _, y in poly)
                    self.assertAlmostEqual(shape.top, drawn, delta=1.5)

    def test_every_leader_ends_on_its_own_body(self):
        for label, world in many_states():
            drawing = render.plan(world)
            for shape in drawing.shapes:
                _, _, x2, y2 = render.leader(shape)
                with self.subTest(state=label, ident=shape.ident):
                    self.assertTrue(_on_body((x2, y2), shape),
                                    "line for %s ends in empty space" % shape.ident)

    def test_a_label_above_a_pyramid_reaches_its_apex(self):
        scene = world.World()
        scene.add("pyramid", "blue", "big", ident="p")
        shape = render.plan(scene).shape_for("p")
        self.assertEqual(shape.label_side, "above")
        _, _, x2, y2 = render.leader(shape)
        self.assertAlmostEqual(x2, shape.cx, delta=0.5)
        self.assertAlmostEqual(y2, shape.roof_y, delta=0.5)   # the apex

    def test_the_aim_follows_the_outline_not_a_box(self):
        """Works for a pyramid and a ball, which are not rectangles."""
        scene = world.World()
        scene.add("pyramid", "blue", "big", ident="p")
        scene.add("ball", "red", "big", ident="s")
        drawing = render.plan(scene)
        for ident in ("p", "s"):
            shape = drawing.shape_for(ident)
            for toward in ((shape.cx - 400, shape.base_y),
                           (shape.cx + 400, shape.base_y),
                           (shape.cx, shape.base_y - 400),
                           (shape.cx - 300, shape.base_y - 300)):
                with self.subTest(ident=ident, toward=toward):
                    point = render.touch_point(shape, toward)
                    self.assertTrue(_on_body(point, shape),
                                    "%s: %s is off the body" % (ident, point))


def _on_body(point, shape, tolerance=1.5):
    """Is ``point`` on the object as drawn (inside, or within a hair of it)?"""
    for poly in render.drawn_body(shape):
        if _inside(point, poly) or _distance(point, poly) <= tolerance:
            return True
    return False


def _inside(point, poly):
    x, y = point
    inside = False
    for index, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(index + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _distance(point, poly):
    px, py = point
    best = float("inf")
    for index, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(index + 1) % len(poly)]
        dx, dy = x2 - x1, y2 - y1
        span = dx * dx + dy * dy
        t = 0.0 if span == 0 else max(0.0, min(1.0,
                                             ((px - x1) * dx + (py - y1) * dy) / span))
        best = min(best, ((px - (x1 + t * dx)) ** 2 + (py - (y1 + t * dy)) ** 2) ** 0.5)
    return best


class TestDrawing(unittest.TestCase):
    def test_the_svg_is_well_formed_xml(self):
        for label, world in many_states()[:6]:
            with self.subTest(state=label):
                ET.fromstring(render.to_svg(world))

    def test_the_drawing_is_deterministic(self):
        first = render.to_svg(BASE.world())
        second = render.to_svg(BASE.world())
        self.assertEqual(first, second)

    def test_labels_are_drawn_after_every_shape(self):
        """Otherwise a stacked object would hide the label above it."""
        svg = render.to_svg(BASE.world())
        last_shape = max(svg.rfind('fill="%s"' % render.colour_of(o.color))
                         for o in BASE.world().actual_objects())
        first_label = svg.find("<text ")
        self.assertLess(last_shape, first_label)

    def test_a_stacked_object_gets_its_label_to_the_side(self):
        """Something is already on top, so 'above' is taken."""
        drawing = render.plan(BASE.world())
        lower = drawing.shape_for("b")     # a is stacked on b
        self.assertEqual(drawing.shape_for("a").label_side, "above")
        self.assertNotEqual(lower.label_side, "above")

    def test_a_stack_is_drawn_as_one_column(self):
        """What rests on what decides the drawing, not a stored coordinate."""
        drawing = render.plan(BASE.world())
        self.assertEqual([drawing.shape_for(i).level for i in ("b", "a")], [0, 1])
        self.assertAlmostEqual(drawing.shape_for("a").cx, drawing.shape_for("b").cx, delta=0.5)

    def test_the_canvas_grows_to_fit_more_columns(self):
        small = render.plan(BASE.world())
        before = len(render.columns(BASE.world()))
        world = BASE.world()
        world.add("cube", "white", "big", ident="f")
        bigger = render.plan(world)
        self.assertEqual(len(render.columns(world)), before + 1)
        self.assertGreaterEqual(bigger.width, small.width - 1)
        self.assertGreaterEqual(bigger.height, small.height - 1)

    def test_colours_come_from_the_palette(self):
        svg = render.to_svg(BASE.world())
        for obj in BASE.world().actual_objects():
            with self.subTest(ident=obj.ident):
                self.assertIn(render.colour_of(obj.color), svg)

    def test_an_unknown_colour_falls_back_rather_than_crashing(self):
        world = BASE.world()
        world.get("a").color = "chartreuse"
        self.assertIn(render.FALLBACK_COLOUR, render.to_svg(world))


class TestRenderCli(unittest.TestCase):
    def test_check_passes_on_a_generated_exam(self):
        out = io.StringIO()
        with _redirect(out):
            code = render_main.main(["--check", "--seed", "3", "--stage", "both"])
        self.assertEqual(code, 0)
        self.assertIn("carries the whole state", out.getvalue())

    def test_writing_a_single_picture(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scene.svg")
            with _redirect(io.StringIO()):
                code = render_main.main(["--scenario", "first-version", "--out", path])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(path))
            with open(path, encoding="utf-8") as handle:
                ET.fromstring(handle.read())

    def test_the_output_extension_decides_the_format(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("PNG output needs Pillow")
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scene.png")
            with _redirect(io.StringIO()):
                code = render_main.main(["--scenario", "first-version", "--out", path])
            self.assertEqual(code, 0)
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(8), b"\x89PNG\r\n\x1a\n")

    def test_writing_both_stages_into_a_directory(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with _redirect(io.StringIO()):
                code = render_main.main(["--seed", "3", "--stage", "both",
                                         "--out-dir", tmp, "--quiet"])
            self.assertEqual(code, 0)
            self.assertEqual(len(os.listdir(tmp)), 2)

    def test_without_a_destination_the_svg_is_printed(self):
        out = io.StringIO()
        with _redirect(out):
            code = render_main.main(["--scenario", "first-version"])
        self.assertEqual(code, 0)
        self.assertIn("<svg", out.getvalue())

    def test_no_labels_still_checks_out(self):
        out = io.StringIO()
        with _redirect(out):
            code = render_main.main(["--check", "--seed", "3", "--no-labels"])
        self.assertEqual(code, 0)

    def test_it_says_how_to_open_the_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with _redirect(out):
                render_main.main(["--scenario", "first-version",
                                  "--out", os.path.join(tmp, "s.svg")])
        self.assertIn("open", out.getvalue())


class _redirect:
    """Tiny context manager so the CLI's prints do not pollute test output."""

    def __init__(self, stream):
        self.stream = stream

    def __enter__(self):
        import contextlib
        self._stdout = contextlib.redirect_stdout(self.stream)
        self._stdout.__enter__()
        return self.stream

    def __exit__(self, *exc):
        return self._stdout.__exit__(*exc)


if __name__ == "__main__":
    unittest.main()
