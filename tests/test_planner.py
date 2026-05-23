import unittest

from drawing.planner import ShapeSpec, stroke_from_spec, toolpath_from_specs


class PlannerTest(unittest.TestCase):
    def test_builds_circle_stroke(self):
        stroke = stroke_from_spec(ShapeSpec(kind="circle", center=(0.0, 0.0), size=0.1))

        self.assertEqual(stroke.points.shape[1], 2)
        self.assertGreater(len(stroke.points), 8)

    def test_builds_multi_shape_toolpath(self):
        path = toolpath_from_specs(
            [
                ShapeSpec(kind="circle", center=(-0.1, 0.0), size=0.05),
                ShapeSpec(kind="triangle", center=(0.1, 0.0), size=0.12),
            ]
        )

        self.assertEqual(path.shape[1], 3)
        self.assertGreater(len(path), 10)


if __name__ == "__main__":
    unittest.main()

