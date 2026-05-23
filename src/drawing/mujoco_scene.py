from __future__ import annotations

from dataclasses import dataclass
import time

import numpy as np

from .shapes import interpolate_polyline


SCENE_XML = """
<mujoco model="drawing_board">
  <compiler angle="radian"/>
  <option timestep="0.005" gravity="0 0 -9.81"/>
  <visual>
    <quality shadowsize="2048"/>
    <map znear="0.01"/>
  </visual>
  <asset>
    <texture name="grid" type="2d" builtin="checker" width="512" height="512"
             rgb1="0.94 0.94 0.90" rgb2="0.82 0.86 0.84"/>
    <material name="paper" texture="grid" texrepeat="7 5" reflectance="0.05"/>
    <material name="ink" rgba="0.05 0.07 0.08 1"/>
    <material name="pen" rgba="0.86 0.12 0.10 1"/>
  </asset>
  <worldbody>
    <light pos="0 -1.2 1.8" dir="0 0 -1"/>
    <camera name="overhead" pos="0 -0.02 1.1" xyaxes="1 0 0 0 1 0"/>
    <geom name="canvas" type="box" pos="0 0 -0.006" size="0.36 0.24 0.006"
          material="paper"/>
    <body name="pen_tip" mocap="true" pos="0 0 0.08">
      <geom name="tip" type="sphere" size="0.012" material="pen"/>
      <geom name="nib" type="cylinder" pos="0 0 -0.025" size="0.004 0.025"
            material="ink"/>
    </body>
  </worldbody>
</mujoco>
"""


PIPER_SCENE_XML = """
<mujoco model="piper_drawing_board">
  <compiler angle="radian"/>
  <option timestep="0.005" gravity="0 0 -9.81"/>
  <visual>
    <quality shadowsize="2048"/>
    <map znear="0.01"/>
  </visual>
  <asset>
    <texture name="grid" type="2d" builtin="checker" width="512" height="512"
             rgb1="0.94 0.94 0.90" rgb2="0.82 0.86 0.84"/>
    <material name="paper" texture="grid" texrepeat="7 5" reflectance="0.05"/>
    <material name="ink" rgba="0.05 0.07 0.08 1"/>
    <material name="arm" rgba="0.24 0.34 0.42 1"/>
    <material name="joint" rgba="0.08 0.11 0.13 1"/>
    <material name="pen" rgba="0.86 0.12 0.10 1"/>
  </asset>
  <worldbody>
    <light pos="0 -1.2 1.8" dir="0 0 -1"/>
    <camera name="overhead" pos="0 -0.04 1.18" xyaxes="1 0 0 0 1 0"/>
    <camera name="side" pos="-0.72 -0.74 0.55" xyaxes="0.72 -0.70 0 0.28 0.29 0.91"/>
    <geom name="canvas" type="box" pos="0 0 -0.006" size="0.36 0.24 0.006"
          material="paper"/>
    <body name="piper_base" pos="-0.45 0 0.035">
      <geom name="base" type="cylinder" size="0.075 0.035" material="joint"/>
      <body name="joint1" pos="0 0 0.055">
        <joint name="joint1" type="hinge" axis="0 0 1" range="-2.8 2.8" damping="1.2"/>
        <geom type="sphere" size="0.045" material="joint"/>
        <body name="joint2" pos="0 0 0.055">
          <joint name="joint2" type="hinge" axis="0 1 0" range="-2.8 2.8" damping="1.2"/>
          <geom type="capsule" fromto="0 0 0 0.34 0 0" size="0.025" material="arm"/>
          <body name="joint3" pos="0.34 0 0">
            <joint name="joint3" type="hinge" axis="0 1 0" range="-3.05 3.05" damping="1.0"/>
            <geom type="sphere" size="0.037" material="joint"/>
            <geom type="capsule" fromto="0 0 0 0.29 0 0" size="0.022" material="arm"/>
            <body name="joint4" pos="0.29 0 0">
              <joint name="joint4" type="hinge" axis="1 0 0" range="-3.0 3.0" damping="0.7"/>
              <geom type="sphere" size="0.03" material="joint"/>
              <body name="joint5" pos="0.055 0 0">
                <joint name="joint5" type="hinge" axis="0 1 0" range="-2.8 2.8" damping="0.7"/>
                <geom type="capsule" fromto="0 0 0 0.14 0 0" size="0.018" material="arm"/>
                <body name="joint6" pos="0.14 0 0">
                  <joint name="joint6" type="hinge" axis="1 0 0" range="-3.14 3.14" damping="0.5"/>
                  <geom type="sphere" size="0.024" material="joint"/>
                  <geom name="pen_mount" type="capsule" fromto="0 0 0 0.06 0 0"
                        size="0.012" material="joint"/>
                  <geom name="pen_body" type="cylinder" pos="0.06 0 -0.055"
                        size="0.006 0.055" material="pen"/>
                  <geom name="nib" type="sphere" pos="0.06 0 -0.115" size="0.008"
                        material="ink"/>
                  <site name="pen_tip" pos="0.06 0 -0.115" size="0.006"
                        rgba="0.02 0.02 0.02 1"/>
                </body>
              </body>
            </body>
          </body>
        </body>
      </body>
    </body>
  </worldbody>
</mujoco>
"""


@dataclass
class DrawingSimulator:
    """Minimal MuJoCo simulator that moves a mocap pen along target points."""

    draw_z: float = 0.018
    travel_z: float = 0.09
    spacing: float = 0.005
    dt: float = 0.005
    seconds_per_meter: float = 7.0

    def __post_init__(self) -> None:
        try:
            import mujoco
        except ImportError as exc:
            raise RuntimeError(
                "mujoco is not installed. Run `python -m pip install -r requirements.txt`."
            ) from exc

        self.mujoco = mujoco
        self.model = mujoco.MjModel.from_xml_string(SCENE_XML)
        self.data = mujoco.MjData(self.model)

    def run(
        self,
        strokes: list[np.ndarray],
        viewer: bool = True,
        hold_after_drawing: bool = False,
    ) -> None:
        points = self._compose_targets(strokes)
        if viewer:
            self._run_viewer(points, hold_after_drawing=hold_after_drawing)
        else:
            self._run_headless(points)

    def _compose_targets(self, strokes: list[np.ndarray]) -> np.ndarray:
        paths = []
        for stroke in strokes:
            paths.append(interpolate_polyline(stroke, self.spacing))
        if not paths:
            return np.zeros((0, 3), dtype=float)
        return np.vstack(paths)

    def _run_headless(self, points: np.ndarray) -> None:
        for point in points:
            self._set_pen(point)
            self.mujoco.mj_step(self.model, self.data)

    def _run_viewer(self, points: np.ndarray, hold_after_drawing: bool) -> None:
        import mujoco.viewer

        with mujoco.viewer.launch_passive(self.model, self.data) as viewer:
            viewer.cam.type = self.mujoco.mjtCamera.mjCAMERA_FIXED
            viewer.cam.fixedcamid = self.model.camera("overhead").id
            drawn = []
            for point in points:
                start = time.time()
                self._set_pen(point)
                self.mujoco.mj_step(self.model, self.data)
                if point[2] <= self.draw_z + 0.01:
                    drawn.append(point.copy())
                self._update_trace(viewer, np.asarray(drawn))
                viewer.sync()
                elapsed = time.time() - start
                time.sleep(max(0.0, self.dt - elapsed))

            while hold_after_drawing and viewer.is_running():
                self._update_trace(viewer, np.asarray(drawn))
                viewer.sync()
                time.sleep(1.0 / 30.0)

    def _set_pen(self, point: np.ndarray) -> None:
        self.data.mocap_pos[0] = point
        self.data.mocap_quat[0] = np.array([1.0, 0.0, 0.0, 0.0])

    def _update_trace(self, viewer, points: np.ndarray) -> None:
        if len(points) < 2:
            viewer.user_scn.ngeom = 0
            return

        max_segments = min(len(points) - 1, len(viewer.user_scn.geoms))
        start_index = len(points) - max_segments - 1
        viewer.user_scn.ngeom = max_segments
        for geom_index in range(max_segments):
            a = points[start_index + geom_index]
            b = points[start_index + geom_index + 1]
            geom = viewer.user_scn.geoms[geom_index]
            self.mujoco.mjv_connector(
                geom,
                self.mujoco.mjtGeom.mjGEOM_CAPSULE,
                0.003,
                a,
                b,
            )
            geom.rgba[:] = np.array([0.02, 0.025, 0.03, 1.0])


@dataclass
class PiperDrawingSimulator:
    """Simplified Piper-style 6DOF arm that follows drawing targets with IK."""

    draw_z: float = 0.018
    travel_z: float = 0.09
    spacing: float = 0.005
    dt: float = 0.005
    ik_iterations: int = 100
    ik_damping: float = 1e-3

    def __post_init__(self) -> None:
        try:
            import mujoco
        except ImportError as exc:
            raise RuntimeError(
                "mujoco is not installed. Run `python -m pip install -r requirements.txt`."
            ) from exc

        self.mujoco = mujoco
        self.model = mujoco.MjModel.from_xml_string(PIPER_SCENE_XML)
        self.data = mujoco.MjData(self.model)
        self.joint_names = [f"joint{i}" for i in range(1, 7)]
        self.joint_ids = np.array([self.model.joint(name).id for name in self.joint_names])
        self.qpos_adrs = np.array([self.model.jnt_qposadr[joint_id] for joint_id in self.joint_ids])
        self.dof_adrs = np.array([self.model.jnt_dofadr[joint_id] for joint_id in self.joint_ids])
        self.joint_ranges = self.model.jnt_range[self.joint_ids]
        self.tip_site_id = self.model.site("pen_tip").id
        self.rest_qpos = np.array([0.0, -0.78, 1.55, 0.0, -0.9, 0.0])
        self._set_qpos(self.rest_qpos)

    def run(
        self,
        strokes: list[np.ndarray],
        viewer: bool = True,
        hold_after_drawing: bool = False,
    ) -> None:
        points = self._compose_targets(strokes)
        if viewer:
            self._run_viewer(points, hold_after_drawing=hold_after_drawing)
        else:
            self._run_headless(points)

    def _compose_targets(self, strokes: list[np.ndarray]) -> np.ndarray:
        paths = []
        for stroke in strokes:
            paths.append(interpolate_polyline(stroke, self.spacing))
        if not paths:
            return np.zeros((0, 3), dtype=float)
        return np.vstack(paths)

    def _run_headless(self, points: np.ndarray) -> None:
        for target in points:
            self._step_to_target(target)

    def _run_viewer(self, points: np.ndarray, hold_after_drawing: bool) -> None:
        import mujoco.viewer

        with mujoco.viewer.launch_passive(self.model, self.data) as viewer:
            viewer.cam.type = self.mujoco.mjtCamera.mjCAMERA_FIXED
            viewer.cam.fixedcamid = self.model.camera("side").id
            drawn = []
            for target in points:
                start = time.time()
                tip = self._step_to_target(target)
                if target[2] <= self.draw_z + 0.01:
                    drawn.append(tip.copy())
                self._update_trace(viewer, np.asarray(drawn))
                viewer.sync()
                elapsed = time.time() - start
                time.sleep(max(0.0, self.dt - elapsed))

            while hold_after_drawing and viewer.is_running():
                self._update_trace(viewer, np.asarray(drawn))
                viewer.sync()
                time.sleep(1.0 / 30.0)

    def _step_to_target(self, target: np.ndarray) -> np.ndarray:
        target = np.asarray(target, dtype=float)
        self._solve_ik(target)
        self.mujoco.mj_step(self.model, self.data)
        return self.data.site_xpos[self.tip_site_id].copy()

    def _solve_ik(self, target: np.ndarray) -> None:
        jacp = np.zeros((3, self.model.nv), dtype=float)
        jacr = np.zeros((3, self.model.nv), dtype=float)
        for _ in range(self.ik_iterations):
            self.mujoco.mj_forward(self.model, self.data)
            tip = self.data.site_xpos[self.tip_site_id]
            err = target - tip
            if np.linalg.norm(err) < 8e-4:
                break

            self.mujoco.mj_jacSite(self.model, self.data, jacp, jacr, self.tip_site_id)
            j = jacp[:, self.dof_adrs]
            lhs = j @ j.T + self.ik_damping * np.eye(3)
            j_pinv = j.T @ np.linalg.inv(lhs)
            primary = j_pinv @ err
            nullspace = np.eye(len(self.dof_adrs)) - j_pinv @ j
            posture = 0.08 * (self.rest_qpos - self.data.qpos[self.qpos_adrs])
            dq = primary + nullspace @ posture
            self._set_qpos(self.data.qpos[self.qpos_adrs] + 0.65 * dq)

    def _set_qpos(self, qpos: np.ndarray) -> None:
        clipped = np.clip(qpos, self.joint_ranges[:, 0], self.joint_ranges[:, 1])
        self.data.qpos[self.qpos_adrs] = clipped
        self.data.qvel[self.dof_adrs] = 0.0
        self.mujoco.mj_forward(self.model, self.data)

    def _update_trace(self, viewer, points: np.ndarray) -> None:
        if len(points) < 2:
            viewer.user_scn.ngeom = 0
            return

        max_segments = min(len(points) - 1, len(viewer.user_scn.geoms))
        start_index = len(points) - max_segments - 1
        viewer.user_scn.ngeom = max_segments
        for geom_index in range(max_segments):
            a = points[start_index + geom_index]
            b = points[start_index + geom_index + 1]
            geom = viewer.user_scn.geoms[geom_index]
            self.mujoco.mjv_connector(
                geom,
                self.mujoco.mjtGeom.mjGEOM_CAPSULE,
                0.003,
                a,
                b,
            )
            geom.rgba[:] = np.array([0.02, 0.025, 0.03, 1.0])
