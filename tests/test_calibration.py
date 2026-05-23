import unittest

import numpy as np

from drawing.calibration import PlaneCalibrator


class PlaneCalibrationTest(unittest.TestCase):
    def test_maps_board_corners_to_canvas_coordinates(self):
        image = np.array(
            [
                [120.0, 80.0],
                [520.0, 90.0],
                [500.0, 360.0],
                [100.0, 340.0],
            ]
        )
        canvas = np.array(
            [
                [-0.2, -0.15],
                [0.2, -0.15],
                [0.2, 0.15],
                [-0.2, 0.15],
            ]
        )

        calibrator = PlaneCalibrator.from_points(image, canvas)
        mapped = calibrator.image_to_canvas(image)

        np.testing.assert_allclose(mapped, canvas, atol=1e-9)


if __name__ == "__main__":
    unittest.main()

