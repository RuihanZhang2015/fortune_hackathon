import unittest

from fastapi.testclient import TestClient

from reachy_fortune.app import app


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


if __name__ == "__main__":
    unittest.main()

