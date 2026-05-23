from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from .shapes import Stroke, circle_points, interpolate_polyline, triangle_points


ShapeKind = Literal["circle", "triangle"]


@dataclass(frozen=True)
class ShapeSpec:
    """A shape request in calibrated canvas coordinates."""

    kind: ShapeKind
    center: tuple[float, float]
    size: float
    rotation: float = 0.0


def stroke_from_spec(spec: ShapeSpec) -> Stroke:
    """Convert a detected/requested shape to a planar drawing stroke.

    `size` means radius for circles and side length for triangles.
    """
    if spec.kind == "circle":
        return circle_points(center=spec.center, radius=spec.size)
    if spec.kind == "triangle":
        return triangle_points(center=spec.center, side=spec.size, rotation=spec.rotation)
    raise ValueError(f"unsupported shape kind {spec.kind!r}")


def toolpath_from_specs(
    specs: list[ShapeSpec],
    draw_z: float = 0.018,
    travel_z: float = 0.09,
    spacing: float = 0.005,
) -> np.ndarray:
    """Build a single 3D pen path from one or more shape requests."""
    paths = []
    for spec in specs:
        stroke = stroke_from_spec(spec)
        lifted = stroke.with_lift(draw_z=draw_z, travel_z=travel_z)
        paths.append(interpolate_polyline(lifted, spacing=spacing))
    if not paths:
        return np.zeros((0, 3), dtype=float)
    return np.vstack(paths)

