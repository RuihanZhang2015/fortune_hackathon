import unittest

from reachy_fortune.pub_to_ngrok import points3d_from_mapped_payload


class PubToNgrokTest(unittest.TestCase):
    def test_converts_mapped_xy_points_to_constant_z_trajectory(self):
        payload = {
            "xy_points": [
                [230.25, -70.65],
                [240.5, -60.0],
            ],
        }

        points = points3d_from_mapped_payload(payload, z_mm=205)

        self.assertEqual(points, [[230.25, -70.65, 205.0], [240.5, -60.0, 205.0]])


if __name__ == "__main__":
    unittest.main()
