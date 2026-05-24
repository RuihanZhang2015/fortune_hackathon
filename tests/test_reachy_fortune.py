import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from reachy_fortune.app import app
from reachy_fortune.render import render_toolpath_png


class ReachyFortuneAppTest(unittest.TestCase):
    def test_robot_draw_returns_tool_call_and_render(self):
        client = TestClient(app)
        response = client.post(
            "/api/robot_draw",
            json={"prompt": "你能给我分析今天的运势", "style": "道教毛笔"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["tool_call"]["type"], "robot_draw")
        self.assertGreater(data["point_count"], 20)
        self.assertIn("玄运图", data["interpretation"])

        image_response = client.get(data["image_url"])
        self.assertEqual(image_response.status_code, 200)
        self.assertEqual(image_response.headers["content-type"], "image/png")

    def test_robot_draw_can_skip_reachy_output(self):
        client = TestClient(app)
        with patch("reachy_fortune.app.reachy.express") as express:
            response = client.post(
                "/api/robot_draw",
                json={"prompt": "今天运势", "reachy_output": False},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["reachy_output"])
        express.assert_not_called()

    def test_robot_draw_default_seed_varies_same_prompt(self):
        client = TestClient(app)
        first = client.post(
            "/api/robot_draw",
            json={"prompt": "今天运势", "reachy_output": False},
        ).json()
        second = client.post(
            "/api/robot_draw",
            json={"prompt": "今天运势", "reachy_output": False},
        ).json()

        self.assertNotEqual(first["drawing_seed"], second["drawing_seed"])
        self.assertNotEqual(first["tool_call"]["xy_points"], second["tool_call"]["xy_points"])

    def test_robot_draw_fixed_seed_is_reproducible(self):
        client = TestClient(app)
        body = {"prompt": "今天运势", "reachy_output": False, "drawing_seed": "debug-seed"}
        first = client.post("/api/robot_draw", json=body).json()
        second = client.post("/api/robot_draw", json=body).json()

        self.assertEqual(first["drawing_seed"], "debug-seed")
        self.assertEqual(first["tool_call"]["xy_points"], second["tool_call"]["xy_points"])

    def test_render_skips_lifted_travel_segments(self):
        payload = {
            "draw_z": 0.018,
            "points": [
                [-0.1, 0.0, 0.018],
                [-0.05, 0.0, 0.018],
                [-0.05, 0.0, 0.09],
                [0.05, 0.0, 0.09],
                [0.05, 0.0, 0.018],
                [0.1, 0.0, 0.018],
            ],
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "render.png"
            render_toolpath_png(payload, path, size=300)
            image = Image.open(path)

        paper = (244, 235, 214)
        self.assertNotEqual(image.getpixel((130, 150)), paper)
        self.assertEqual(image.getpixel((150, 150)), paper)
        self.assertNotEqual(image.getpixel((170, 150)), paper)


if __name__ == "__main__":
    unittest.main()
