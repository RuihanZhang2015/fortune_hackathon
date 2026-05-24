import unittest

from drawing.map_toolpath import map_toolpath_payload


class MapToolpathTest(unittest.TestCase):
    def test_maps_canvas_to_target_image_coordinates(self):
        payload = {
            "units": "meters",
            "draw_z": 0.018,
            "points": [
                [-0.23, 0.17, 0.018],
                [0.23, -0.17, 0.018],
            ],
        }

        mapped = map_toolpath_payload(payload)

        self.assertEqual(mapped["path_mode"], "straight_line_segments")
        self.assertTrue(mapped["swap_xy"])
        self.assertEqual(mapped["xy_segments"], [[[200.0, -130.0], [400.0, 130.0]]])
        self.assertEqual(mapped["xy_points"], [[200.0, -130.0], [400.0, 130.0]])

if __name__ == "__main__":
    unittest.main()
