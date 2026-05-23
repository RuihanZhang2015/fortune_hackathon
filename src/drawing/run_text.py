from __future__ import annotations

import argparse

from .mujoco_scene import DrawingSimulator, PiperDrawingSimulator
from .text_to_drawing import (
    strokes_from_payload,
    toolpath_payload_from_text,
    write_toolpath_json,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile natural language to drawing toolpaths.")
    parser.add_argument("prompt", help="Natural language drawing request.")
    parser.add_argument("--output", default="outputs/toolpath.json")
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--hold", action="store_true")
    parser.add_argument("--robot", choices=["piper", "mocap"], default="piper")
    args = parser.parse_args()

    payload = toolpath_payload_from_text(args.prompt)
    write_toolpath_json(payload, args.output)
    print(f"wrote {args.output}")
    print(payload["reading"])

    if args.simulate:
        sim_cls = PiperDrawingSimulator if args.robot == "piper" else DrawingSimulator
        sim = sim_cls(draw_z=payload["draw_z"], travel_z=payload["travel_z"])
        sim.run(
            strokes_from_payload(payload),
            viewer=not args.headless,
            hold_after_drawing=args.hold,
        )


if __name__ == "__main__":
    main()

