from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


Array = np.ndarray


@dataclass(frozen=True)
class Stroke:
    """A pen trajectory in canvas coordinates.

    Points are shaped `(N, 2)` and use meters on the drawing plane.
    """

    points: Array
    closed: bool = True

    def with_lift(self, draw_z: float = 0.012, travel_z: float = 0.08) -> Array:
        """Return `(N + 2, 3)` points with safe approach and retract moves."""
        if len(self.points) == 0:
            return np.zeros((0, 3), dtype=float)

        xy = np.asarray(self.points, dtype=float)
        z = np.full((len(xy), 1), draw_z, dtype=float)
        drawing = np.hstack([xy, z])

        start = np.array([[xy[0, 0], xy[0, 1], travel_z]], dtype=float)
        end = np.array([[xy[-1, 0], xy[-1, 1], travel_z]], dtype=float)
        return np.vstack([start, drawing, end])


def circle_points(
    center: tuple[float, float] = (0.0, 0.0),
    radius: float = 0.12,
    samples: int = 160,
) -> Stroke:
    """Generate a closed circular drawing path."""
    if radius <= 0:
        raise ValueError("radius must be positive")
    if samples < 8:
        raise ValueError("samples must be at least 8")

    theta = np.linspace(0.0, 2.0 * math.pi, samples, endpoint=True)
    points = np.column_stack(
        [
            center[0] + radius * np.cos(theta),
            center[1] + radius * np.sin(theta),
        ]
    )
    return Stroke(points=points, closed=True)


def triangle_points(
    center: tuple[float, float] = (0.0, 0.0),
    side: float = 0.26,
    rotation: float = math.pi / 2.0,
) -> Stroke:
    """Generate an equilateral triangle drawing path."""
    if side <= 0:
        raise ValueError("side must be positive")

    radius = side / math.sqrt(3.0)
    angles = rotation + np.array([0.0, 2.0 * math.pi / 3.0, 4.0 * math.pi / 3.0, 0.0])
    points = np.column_stack(
        [
            center[0] + radius * np.cos(angles),
            center[1] + radius * np.sin(angles),
        ]
    )
    return Stroke(points=points, closed=True)


def polyline_points(points: list[tuple[float, float]], closed: bool = False) -> Stroke:
    """Create a stroke from explicit canvas points."""
    if len(points) < 2:
        raise ValueError("at least two points are required")
    pts = np.asarray(points, dtype=float)
    if closed and not np.allclose(pts[0], pts[-1]):
        pts = np.vstack([pts, pts[0]])
    return Stroke(points=pts, closed=closed)


def star_points(
    center: tuple[float, float] = (0.0, 0.0),
    outer_radius: float = 0.06,
    inner_radius: float | None = None,
    tips: int = 5,
    rotation: float = math.pi / 2.0,
) -> Stroke:
    """Generate a closed star path."""
    if outer_radius <= 0:
        raise ValueError("outer_radius must be positive")
    if tips < 4:
        raise ValueError("tips must be at least 4")
    inner = inner_radius if inner_radius is not None else outer_radius * 0.42
    if inner <= 0:
        raise ValueError("inner_radius must be positive")

    angles = rotation + np.arange(tips * 2 + 1) * math.pi / tips
    radii = np.where(np.arange(tips * 2 + 1) % 2 == 0, outer_radius, inner)
    points = np.column_stack(
        [
            center[0] + radii * np.cos(angles),
            center[1] + radii * np.sin(angles),
        ]
    )
    return Stroke(points=points, closed=True)


def arc_points(
    center: tuple[float, float],
    radius: float,
    start_angle: float,
    end_angle: float,
    samples: int = 48,
) -> Stroke:
    """Generate an open circular arc."""
    if radius <= 0:
        raise ValueError("radius must be positive")
    if samples < 2:
        raise ValueError("samples must be at least 2")
    theta = np.linspace(start_angle, end_angle, samples)
    points = np.column_stack(
        [
            center[0] + radius * np.cos(theta),
            center[1] + radius * np.sin(theta),
        ]
    )
    return Stroke(points=points, closed=False)


def wave_points(
    start: tuple[float, float],
    width: float,
    amplitude: float = 0.018,
    cycles: float = 2.0,
    samples: int = 80,
) -> Stroke:
    """Generate an open sine-wave stroke."""
    if width <= 0:
        raise ValueError("width must be positive")
    x = np.linspace(start[0], start[0] + width, samples)
    phase = np.linspace(0.0, 2.0 * math.pi * cycles, samples)
    y = start[1] + amplitude * np.sin(phase)
    return Stroke(points=np.column_stack([x, y]), closed=False)


def interpolate_polyline(points: Array, spacing: float = 0.006) -> Array:
    """Resample a polyline so consecutive points are roughly `spacing` apart."""
    pts = np.asarray(points, dtype=float)
    if pts.ndim != 2 or pts.shape[1] not in (2, 3):
        raise ValueError("points must be shaped (N, 2) or (N, 3)")
    if len(pts) < 2:
        return pts.copy()
    if spacing <= 0:
        raise ValueError("spacing must be positive")

    output = [pts[0]]
    for start, end in zip(pts[:-1], pts[1:]):
        delta = end - start
        length = float(np.linalg.norm(delta))
        if length == 0.0:
            continue
        steps = max(1, int(math.ceil(length / spacing)))
        for i in range(1, steps + 1):
            output.append(start + delta * (i / steps))
    return np.asarray(output, dtype=float)


def demo_strokes(shape: str) -> list[Stroke]:
    """Return one or more centered demo strokes."""
    if shape == "circle":
        return [circle_points(center=(-0.12, 0.0), radius=0.09)]
    if shape == "triangle":
        return [triangle_points(center=(0.12, 0.0), side=0.19)]
    if shape == "both":
        return [
            circle_points(center=(-0.12, 0.0), radius=0.09),
            triangle_points(center=(0.12, 0.0), side=0.19),
        ]
    raise ValueError(f"unknown shape {shape!r}; choose circle, triangle, or both")
