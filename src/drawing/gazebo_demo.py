from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
WORLD_PATH = ROOT / "gazebo" / "fortune_pick_draw.world"
PIPER_URDF = Path("/Users/ruihanzhang/Documents/Gazebo/piper_ros/src/piper_description/urdf/piper_description.urdf")
PIPER_MESH_ROOT = Path("/Users/ruihanzhang/Documents/Gazebo/piper_ros/src/piper_description/meshes")


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
    for model_name in [
        "piper_base",
        "piper_shoulder",
        "piper_upper_arm",
        "piper_elbow",
        "piper_forearm",
        "piper_wrist",
        "ghost_gripper",
    ]:
        world_text = _remove_model(world_text, model_name)
    trace = _trace_sdf(segments)
    piper = PiperVisualKinematics()
    exact_models = piper.model_sdf()
    output.write_text(
        world_text.replace("  </world>", f"{trace}\n{exact_models}\n  </world>"),
        encoding="utf-8",
    )
    return output


def _remove_model(world_text: str, model_name: str) -> str:
    marker = f'    <model name="{model_name}">'
    start = world_text.find(marker)
    if start < 0:
        return world_text
    end = world_text.find("    </model>", start)
    if end < 0:
        return world_text
    return world_text[:start] + world_text[end + len("    </model>\n"):]


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
    piper = PiperVisualKinematics()
    q = np.array([0.0, 1.05, -1.15, 0.0, 0.25, 0.0, 0.012, -0.012])
    for index, (pos, rpy) in enumerate(poses):
        gripper_pos = pos + np.array([0.0, 0.0, 0.09])
        q = piper.solve_for_gripper(gripper_pos, q)
        req = (
            "pose { " + _pose_request("pen", pos, rpy) + " } "
            + piper.pose_vector(q)
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


class PiperVisualKinematics:
    def __init__(self) -> None:
        self.base_pose = _transform(np.array([-0.43, -0.23, 0.035]), _rpy_matrix(0.0, 0.0, 0.0))
        self.root = ET.parse(PIPER_URDF).getroot()
        self.links = ["base_link", "link1", "link2", "link3", "link4", "link5", "link6", "gripper_base", "link7", "link8"]
        self.active_joints = ["joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "joint7", "joint8"]
        self.joints = self._parse_joints()
        self.meshes = self._parse_meshes()

    def model_sdf(self) -> str:
        parts = []
        for link in self.links:
            mesh = self.meshes.get(link)
            if mesh is None:
                continue
            parts.append(
                f"""
    <model name="piper_exact_{link}">
      <static>false</static>
      <link name="{link}">
        <visual name="visual">
          <geometry><mesh><uri>file://{mesh}</uri></mesh></geometry>
          <material>
            <ambient>0.70 0.74 0.86 1</ambient>
            <diffuse>0.70 0.74 0.86 1</diffuse>
          </material>
        </visual>
      </link>
    </model>"""
            )
        return "".join(parts)

    def pose_vector(self, q: np.ndarray) -> str:
        transforms = self.forward(q)
        pieces = []
        for link in self.links:
            if link not in transforms or link not in self.meshes:
                continue
            pos, rpy = _pose_from_transform(transforms[link])
            pieces.append("pose { " + _pose_request(f"piper_exact_{link}", pos, rpy) + " }")
        return " ".join(pieces)

    def solve_for_gripper(self, target: np.ndarray, previous_q: np.ndarray) -> np.ndarray:
        try:
            from scipy.optimize import least_squares
        except ImportError:
            return previous_q

        target = np.asarray(target, dtype=float)
        lower = np.array([-2.618, 0.0, -2.967, -1.745, -1.22, -2.0944, 0.0, -0.035])
        upper = np.array([2.618, 3.14, 0.0, 1.745, 1.22, 2.0944, 0.035, 0.0])
        rest = np.array([0.0, 1.15, -1.25, 0.0, 0.25, 0.0, 0.012, -0.012])

        def residual(q: np.ndarray) -> np.ndarray:
            transforms = self.forward(q)
            gripper = transforms["gripper_base"][:3, 3]
            link7 = transforms["link7"][:3, 3]
            link8 = transforms["link8"][:3, 3]
            finger_center = (link7 + link8) / 2.0
            pos_err = finger_center - target
            posture = 0.015 * (q - rest)
            return np.concatenate([pos_err, posture])

        result = least_squares(
            residual,
            np.clip(previous_q, lower, upper),
            bounds=(lower, upper),
            max_nfev=35,
            xtol=1e-4,
            ftol=1e-4,
            gtol=1e-4,
        )
        return result.x

    def forward(self, q: np.ndarray) -> dict[str, np.ndarray]:
        q_by_joint = dict(zip(self.active_joints, q))
        transforms = {"dummy_link": self.base_pose}
        remaining = dict(self.joints)
        while remaining:
            progressed = False
            for name, joint in list(remaining.items()):
                parent = joint["parent"]
                child = joint["child"]
                if parent not in transforms:
                    continue
                motion = np.eye(4)
                if joint["type"] == "revolute":
                    motion = _transform(np.zeros(3), _axis_angle(joint["axis"], q_by_joint.get(name, 0.0)))
                elif joint["type"] == "prismatic":
                    motion = _transform(joint["axis"] * q_by_joint.get(name, 0.0), np.eye(3))
                transforms[child] = transforms[parent] @ joint["origin"] @ motion
                remaining.pop(name)
                progressed = True
            if not progressed:
                break
        return transforms

    def _parse_joints(self) -> dict[str, dict]:
        joints = {}
        for joint in self.root.findall("joint"):
            name = joint.attrib["name"]
            origin = joint.find("origin")
            xyz = _attr_vec(origin, "xyz", [0.0, 0.0, 0.0])
            rpy = _attr_vec(origin, "rpy", [0.0, 0.0, 0.0])
            axis = _attr_vec(joint.find("axis"), "xyz", [0.0, 0.0, 1.0])
            joints[name] = {
                "type": joint.attrib.get("type", "fixed"),
                "parent": joint.find("parent").attrib["link"],
                "child": joint.find("child").attrib["link"],
                "origin": _transform(xyz, _rpy_matrix(*rpy)),
                "axis": axis,
            }
        return joints

    def _parse_meshes(self) -> dict[str, Path]:
        meshes = {}
        for link in self.root.findall("link"):
            visual = link.find("visual")
            if visual is None:
                continue
            mesh = visual.find("geometry/mesh")
            if mesh is None:
                continue
            filename = mesh.attrib["filename"]
            if filename.startswith("package://piper_description/meshes/"):
                meshes[link.attrib["name"]] = PIPER_MESH_ROOT / filename.rsplit("/", 1)[-1]
        return meshes


def _quat_from_rpy(roll: float, pitch: float, yaw: float) -> tuple[float, float, float, float]:
    cr, sr = math.cos(roll / 2.0), math.sin(roll / 2.0)
    cp, sp = math.cos(pitch / 2.0), math.sin(pitch / 2.0)
    cy, sy = math.cos(yaw / 2.0), math.sin(yaw / 2.0)
    qw = cr * cp * cy + sr * sp * sy
    qx = sr * cp * cy - cr * sp * sy
    qy = cr * sp * cy + sr * cp * sy
    qz = cr * cp * sy - sr * sp * cy
    return qx, qy, qz, qw


def _attr_vec(element, attr: str, default: list[float]) -> np.ndarray:
    if element is None or attr not in element.attrib:
        return np.asarray(default, dtype=float)
    return np.asarray([float(value) for value in element.attrib[attr].split()], dtype=float)


def _transform(xyz: np.ndarray, rotation: np.ndarray) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = xyz
    return matrix


def _rpy_matrix(roll: float, pitch: float, yaw: float) -> np.ndarray:
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], dtype=float)
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], dtype=float)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]], dtype=float)
    return rz @ ry @ rx


def _axis_angle(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = np.asarray(axis, dtype=float)
    norm = float(np.linalg.norm(axis))
    if norm < 1e-12:
        return np.eye(3)
    x, y, z = axis / norm
    c, s = math.cos(angle), math.sin(angle)
    c1 = 1.0 - c
    return np.array(
        [
            [c + x * x * c1, x * y * c1 - z * s, x * z * c1 + y * s],
            [y * x * c1 + z * s, c + y * y * c1, y * z * c1 - x * s],
            [z * x * c1 - y * s, z * y * c1 + x * s, c + z * z * c1],
        ],
        dtype=float,
    )


def _pose_from_transform(matrix: np.ndarray) -> tuple[np.ndarray, tuple[float, float, float]]:
    rot = matrix[:3, :3]
    sy = math.sqrt(rot[0, 0] * rot[0, 0] + rot[1, 0] * rot[1, 0])
    if sy > 1e-8:
        roll = math.atan2(rot[2, 1], rot[2, 2])
        pitch = math.atan2(-rot[2, 0], sy)
        yaw = math.atan2(rot[1, 0], rot[0, 0])
    else:
        roll = math.atan2(-rot[1, 2], rot[1, 1])
        pitch = math.atan2(-rot[2, 0], sy)
        yaw = 0.0
    return matrix[:3, 3].copy(), (roll, pitch, yaw)


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
