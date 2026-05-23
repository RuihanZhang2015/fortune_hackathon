from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import time

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
WORLD_PATH = ROOT / "gazebo" / "fortune_pick_draw.world"


def main() -> None:
    parser = argparse.ArgumentParser(description="Drive a Gazebo pen pick-up and drawing demo.")
    parser.add_argument("--toolpath", default="outputs/fortune.json")
    parser.add_argument("--world", default=str(WORLD_PATH))
    parser.add_argument("--world-name", default="fortune_pick_draw")
    parser.add_argument("--samples", type=int, default=90, help="Drawing pose samples for replay speed.")
    parser.add_argument("--no-launch", action="store_true", help="Use an already running Gazebo world.")
    parser.add_argument("--headless", action="store_true", help="Launch gz sim without GUI.")
    args = parser.parse_args()

    payload = _load_payload(Path(args.toolpath))
    points = np.asarray(payload["points"], dtype=float)
    poses = _build_pick_and_draw_poses(points, drawing_samples=args.samples)
    ink_segments = _ink_segments(points)

    process = None
    launch_world = Path(args.world)
    if not args.no_launch:
        launch_world = _write_world_with_trace(Path(args.world), ink_segments)
        process = _launch_gazebo(launch_world, headless=args.headless)
        time.sleep(3.0)

    try:
        _play_pen_and_gripper(args.world_name, poses)
        print("Gazebo pick-up and drawing replay finished.")
    finally:
        if process is not None:
            print("Gazebo is still running. Close the window when done.")


def _load_payload(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"toolpath not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _build_pick_and_draw_poses(
    points: np.ndarray,
    drawing_samples: int,
) -> list[tuple[np.ndarray, tuple[float, float, float]]]:
    draw_points = points[points[:, 2] <= 0.03]
    first = draw_points[0] if len(draw_points) else points[0]
    pen_rest = np.array([-0.33, -0.22, 0.035])
    above_rest = np.array([-0.33, -0.22, 0.16])
    above_first = np.array([first[0], first[1], 0.16])

    poses = []
    poses += _segment(pen_rest, above_rest, 12, pitch=math.pi / 2.0)
    poses += _segment(above_rest, above_rest + np.array([0.0, 0.0, 0.08]), 10, pitch=0.0)
    poses += _segment(above_rest + np.array([0.0, 0.0, 0.08]), above_first, 22, pitch=0.0)

    sampled = points[:: max(1, len(points) // drawing_samples)]
    for point in sampled:
        # Gazebo pen link origin is at the pen center; tip is 8 cm below it.
        center = np.array([point[0], point[1], point[2] + 0.08])
        poses.append((center, (0.0, 0.0, 0.0)))

    final = poses[-1][0]
    poses += _segment(final, final + np.array([0.0, 0.0, 0.12]), 16, pitch=0.0)
    return poses


def _gripper_poses(
    pen_poses: list[tuple[np.ndarray, tuple[float, float, float]]]
) -> list[tuple[np.ndarray, tuple[float, float, float]]]:
    gripper = []
    for pos, rpy in pen_poses:
        gripper.append((pos + np.array([0.0, 0.0, 0.09]), rpy))
    return gripper


def _segment(
    start: np.ndarray,
    end: np.ndarray,
    steps: int,
    pitch: float,
) -> list[tuple[np.ndarray, tuple[float, float, float]]]:
    return [
        (start + (end - start) * (i / max(1, steps - 1)), (0.0, pitch, 0.0))
        for i in range(steps)
    ]


def _ink_segments(points: np.ndarray) -> list[tuple[np.ndarray, float, float]]:
    draw = points[points[:, 2] <= 0.03]
    if len(draw) < 2:
        return []
    stride = max(1, len(draw) // 420)
    draw = draw[::stride]
    segments = []
    for a, b in zip(draw[:-1], draw[1:]):
        delta = b[:2] - a[:2]
        length = float(np.linalg.norm(delta))
        if length < 0.002 or length > 0.04:
            continue
        center = np.array([(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, 0.006])
        yaw = math.atan2(delta[1], delta[0])
        segments.append((center, length, yaw))
    return segments


def _launch_gazebo(world: Path, headless: bool) -> subprocess.Popen:
    cmd = ["gz", "sim", str(world)]
    if headless:
        cmd.insert(2, "-s")
    return subprocess.Popen(cmd, cwd=str(ROOT))


def _write_world_with_trace(world: Path, segments: list[tuple[np.ndarray, float, float]]) -> Path:
    output = ROOT / "outputs" / "gazebo_fortune_pick_draw.world"
    output.parent.mkdir(parents=True, exist_ok=True)
    world_text = world.read_text(encoding="utf-8")
    trace = _trace_sdf(segments)
    output.write_text(world_text.replace("  </world>", f"{trace}\n  </world>"), encoding="utf-8")
    return output


def _trace_sdf(segments: list[tuple[np.ndarray, float, float]]) -> str:
    visuals = []
    for index, (center, length, yaw) in enumerate(segments):
        visuals.append(
            f"""
        <visual name='ink_{index}'>
          <pose>{center[0]:.6f} {center[1]:.6f} {center[2]:.6f} 0 0 {yaw:.6f}</pose>
          <geometry><box><size>{length:.6f} 0.003 0.002</size></box></geometry>
          <material><diffuse>0.02 0.018 0.015 1</diffuse></material>
        </visual>"""
        )
    return "<model name='ink_trace'><static>true</static><link name='ink_link'>" + "".join(visuals) + "</link></model>"


def _play_pen_and_gripper(
    world_name: str,
    poses: list[tuple[np.ndarray, tuple[float, float, float]]],
) -> None:
    total = len(poses)
    for index, (pos, rpy) in enumerate(poses):
        gripper_pos = pos + np.array([0.0, 0.0, 0.09])
        req = (
            "pose { " + _pose_request("pen", pos, rpy) + " } "
            "pose { " + _pose_request("ghost_gripper", gripper_pos, rpy) + " }"
        )
        _gz_service(
            f"/world/{world_name}/set_pose_vector",
            "gz.msgs.Pose_V",
            "gz.msgs.Boolean",
            req,
            timeout=1000,
            quiet=True,
        )
        time.sleep(0.012)
        if index % 25 == 0 or index == total - 1:
            print(f"Gazebo replay {index + 1}/{total}")


def _pose_request(model_name: str, pos: np.ndarray, rpy: tuple[float, float, float]) -> str:
    qx, qy, qz, qw = _quat_from_rpy(*rpy)
    return (
        f'name: "{model_name}" '
        f'position {{ x: {pos[0]:.6f} y: {pos[1]:.6f} z: {pos[2]:.6f} }} '
        f'orientation {{ x: {qx:.8f} y: {qy:.8f} z: {qz:.8f} w: {qw:.8f} }}'
    )


def _quat_from_rpy(roll: float, pitch: float, yaw: float) -> tuple[float, float, float, float]:
    cr, sr = math.cos(roll / 2.0), math.sin(roll / 2.0)
    cp, sp = math.cos(pitch / 2.0), math.sin(pitch / 2.0)
    cy, sy = math.cos(yaw / 2.0), math.sin(yaw / 2.0)
    qw = cr * cp * cy + sr * sp * sy
    qx = sr * cp * cy - cr * sp * sy
    qy = cr * sp * cy + sr * cp * sy
    qz = cr * cp * sy - sr * sp * cy
    return qx, qy, qz, qw


def _gz_service(
    service: str,
    reqtype: str,
    reptype: str,
    req: str,
    timeout: int,
    quiet: bool = False,
) -> None:
    cmd = [
        "gz",
        "service",
        "-s",
        service,
        "--reqtype",
        reqtype,
        "--reptype",
        reptype,
        "--timeout",
        str(timeout),
        "--req",
        req,
    ]
    result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)
    if result.returncode != 0 and not quiet:
        print(result.stderr.strip() or result.stdout.strip())


if __name__ == "__main__":
    main()
