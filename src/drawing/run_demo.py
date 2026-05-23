from __future__ import annotations

import argparse

from .mujoco_scene import DrawingSimulator, PiperDrawingSimulator
from .shapes import demo_strokes


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw simple shapes in MuJoCo.")
    parser.add_argument("--shape", choices=["circle", "triangle", "both"], default="both")
    parser.add_argument(
        "--robot",
        choices=["mocap", "piper"],
        default="piper",
        help="Use a direct mocap pen or a simplified Piper-style arm.",
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--hold",
        action="store_true",
        help="Keep the viewer open after drawing until the window is closed.",
    )
    args = parser.parse_args()

    strokes = [
        stroke.with_lift(draw_z=0.018, travel_z=0.09)
        for stroke in demo_strokes(args.shape)
    ]
    sim_cls = PiperDrawingSimulator if args.robot == "piper" else DrawingSimulator
    sim = sim_cls(draw_z=0.018, travel_z=0.09)
    sim.run(strokes, viewer=not args.headless, hold_after_drawing=args.hold)


if __name__ == "__main__":
    main()
