import unittest

import numpy as np

from drawing.shapes import circle_points, interpolate_polyline, triangle_points


class ShapeGenerationTest(unittest.TestCase):
    def test_circle_is_closed_and_has_requested_radius(self):
        stroke = circle_points(center=(0.1, -0.2), radius=0.05, samples=32)

        np.testing.assert_allclose(stroke.points[0], stroke.points[-1], atol=1e-12)
        radii = np.linalg.norm(stroke.points - np.array([0.1, -0.2]), axis=1)
        np.testing.assert_allclose(radii, 0.05, atol=1e-12)

    def test_triangle_is_closed(self):
        stroke = triangle_points(side=0.3)

        self.assertEqual(stroke.points.shape, (4, 2))
        np.testing.assert_allclose(stroke.points[0], stroke.points[-1], atol=1e-12)

    def test_interpolation_keeps_endpoints(self):
        points = np.array([[0.0, 0.0], [0.1, 0.0]])
        resampled = interpolate_polyline(points, spacing=0.02)

        np.testing.assert_allclose(resampled[0], points[0])
        np.testing.assert_allclose(resampled[-1], points[-1])
        self.assertGreater(len(resampled), len(points))


if __name__ == "__main__":
    unittest.main()

