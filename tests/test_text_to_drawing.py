import unittest
from datetime import date

import numpy as np

from drawing.text_to_drawing import (
    plan_from_text,
    strokes_from_payload,
    toolpath_payload_from_text,
)


class TextToDrawingTest(unittest.TestCase):
    def test_fortune_prompt_builds_robot_payload(self):
        payload = toolpath_payload_from_text(
            "给我一些今天的运势分析，帮我画一个画",
            today=date(2026, 5, 23),
        )

        self.assertEqual(payload["format"], "piper_toolpath_v1")
        self.assertEqual(payload["frame"], "canvas")
        self.assertIn("今日玄运", payload["reading"])
        self.assertIn("太极印", payload["interpretation"])
        self.assertGreaterEqual(len(payload["symbols"]), 5)
        self.assertGreater(len(payload["points"]), 50)

        points = np.asarray(payload["points"])
        self.assertEqual(points.shape[1], 3)
        self.assertGreater(points[:, 2].max(), points[:, 2].min())

    def test_payload_round_trips_to_sim_strokes(self):
        payload = toolpath_payload_from_text("circle", today=date(2026, 5, 23))
        strokes = strokes_from_payload(payload)

        self.assertEqual(len(strokes), 1)
        self.assertEqual(strokes[0].shape[1], 3)

    def test_unknown_prompt_still_creates_a_plan(self):
        plan = plan_from_text("draw my mood", today=date(2026, 5, 23))

        self.assertGreaterEqual(len(plan.strokes), 1)


if __name__ == "__main__":
    unittest.main()
