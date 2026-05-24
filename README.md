# MuJoCo Drawing Hackathon Prototype

This repo contains a small simulation scaffold for drawing simple shapes on a
flat canvas. It is designed so the geometry and camera calibration can be
tested without robot hardware, then reused with an Agile Piper controller.

## What works now

- Generate pen paths for circles and triangles in canvas coordinates.
- Map camera pixels to canvas coordinates with a planar homography.
- Run a MuJoCo demo where a mocap-driven pen tip traces the path over a board.

## Install

```bash
python -m pip install -r requirements.txt
```

If `mujoco` is not installed, the geometry and calibration tests still run.

## Run tests

```bash
python -m unittest discover -s tests
```

## Run the MuJoCo drawing demo

```bash
python -m drawing.run_demo --shape circle
python -m drawing.run_demo --shape triangle
python -m drawing.run_demo --shape both
```

Use `--headless` to run the trajectory without opening the interactive viewer.

```bash
python -m drawing.run_demo --shape both --headless
```

## Natural language to robot trajectory

```bash
python -m drawing.run_text "给我一些今天的运势分析，帮我画一个画" --output outputs/fortune.json
```

The output is a robot-parseable JSON payload:

```json
{
  "format": "piper_toolpath_v1",
  "units": "meters",
  "frame": "canvas",
  "points": [[0.1, 0.0, 0.09], [0.1, 0.0, 0.018]]
}
```

Preview that same natural-language request in MuJoCo:

```bash
python -m drawing.run_text "给我一些今天的运势分析，帮我画一个画" --simulate --hold
```

## Gazebo pick-up and drawing demo

This launches a Gazebo world with a table, paper, pen, ghost gripper, and ink
trace. The pen is moved through a pick-up motion, then follows the generated
fortune toolpath over the paper.

```bash
python -m drawing.gazebo_demo --toolpath outputs/fortune.json
```

Use `--headless` to run the Gazebo server without the GUI.

## Reachy Mini live fortune conversation

This starts a local browser UI for microphone input, OpenAI Realtime voice
conversation, Reachy Mini expressive motion, and the `robot_draw` tool call.

```bash
export OPENAI_API_KEY=...
python -m reachy_fortune.app
```

For noisy rooms, tune the Realtime VAD before launch:

```bash
export OPENAI_VAD_THRESHOLD=0.8
export OPENAI_VAD_SILENCE_DURATION_MS=1000
export OPENAI_VAD_INTERRUPT_RESPONSE=false
export OPENAI_NOISE_REDUCTION=far_field
```

Open `http://127.0.0.1:8787`, click `Connect voice`, then ask:

```text
你能给我分析今天的运势吗？
```

When the model calls `robot_draw`, the backend generates:

- a robot-parseable XY trajectory in `outputs/reachy_fortune/latest_fortune_toolpath.json`
- a rendered preview in `outputs/reachy_fortune/latest_fortune.png`
- a mystical Chinese interpretation for Reachy to speak

Route the computer audio output to Reachy Mini's speaker so the Realtime voice
comes out of Reachy. If the Reachy Mini Python SDK is installed, the backend
also sends simple emotional motion cues; otherwise it runs in dry-run mode.

## Coordinate model

Canvas coordinates are meters in the drawing plane:

- `x`: left/right on the board.
- `y`: front/back on the board.
- `z`: pen height, handled by the simulator/controller.

For camera input, collect at least four known point correspondences:

- image pixels, e.g. board corner detections `(u, v)`.
- matching canvas coordinates in meters `(x, y)`.

Then use `drawing.calibration.PlaneCalibrator` to map detections into drawing
coordinates.

```python
import numpy as np

from drawing.calibration import PlaneCalibrator
from drawing.planner import ShapeSpec, toolpath_from_specs

image_corners = np.array([[120, 80], [520, 90], [500, 360], [100, 340]])
canvas_corners = np.array([[-0.2, -0.15], [0.2, -0.15], [0.2, 0.15], [-0.2, 0.15]])
calibrator = PlaneCalibrator.from_points(image_corners, canvas_corners)

circle_center_px = np.array([310, 210])
circle_center_xy = calibrator.image_to_canvas(circle_center_px)

toolpath = toolpath_from_specs([
    ShapeSpec(kind="circle", center=tuple(circle_center_xy), size=0.06),
    ShapeSpec(kind="triangle", center=(0.1, 0.0), size=0.14),
])
```

## Agile Piper integration point

`drawing.mujoco_scene.DrawingSimulator` currently drives a MuJoCo mocap body as
the pen tip. For the real Agile Piper model, keep the path generation and
calibration modules, then replace the mocap update with one of:

- end-effector IK target commands in simulation, or
- robot joint commands from your Agile Piper SDK/controller.

The contract is simple: follow a sequence of 3D tool-tip targets over time.
