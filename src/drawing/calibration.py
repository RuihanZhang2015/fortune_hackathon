from __future__ import annotations

from dataclasses import dataclass

import numpy as np


Array = np.ndarray


def estimate_homography(image_points: Array, plane_points: Array) -> Array:
    """Estimate a projective map from image pixels `(u, v)` to plane `(x, y)`.

    Uses normalized DLT. At least four non-collinear correspondences are needed.
    """
    src = np.asarray(image_points, dtype=float)
    dst = np.asarray(plane_points, dtype=float)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 2:
        raise ValueError("image_points and plane_points must both be shaped (N, 2)")
    if len(src) < 4:
        raise ValueError("at least four point correspondences are required")

    src_n, t_src = _normalize_points(src)
    dst_n, t_dst = _normalize_points(dst)

    rows = []
    for (u, v), (x, y) in zip(src_n, dst_n):
        rows.append([-u, -v, -1.0, 0.0, 0.0, 0.0, x * u, x * v, x])
        rows.append([0.0, 0.0, 0.0, -u, -v, -1.0, y * u, y * v, y])
    _, _, vh = np.linalg.svd(np.asarray(rows, dtype=float))
    h_norm = vh[-1].reshape(3, 3)

    h = np.linalg.inv(t_dst) @ h_norm @ t_src
    return h / h[2, 2]


def apply_homography(h: Array, image_points: Array) -> Array:
    """Apply a homography to one or more image points."""
    matrix = np.asarray(h, dtype=float)
    pts = np.asarray(image_points, dtype=float)
    single = pts.ndim == 1
    pts = np.atleast_2d(pts)
    if matrix.shape != (3, 3) or pts.shape[1] != 2:
        raise ValueError("h must be (3, 3) and image_points must be (..., 2)")

    homog = np.column_stack([pts, np.ones(len(pts), dtype=float)])
    mapped = (matrix @ homog.T).T
    mapped = mapped[:, :2] / mapped[:, 2:3]
    return mapped[0] if single else mapped


@dataclass(frozen=True)
class PlaneCalibrator:
    """Pixel-to-canvas mapper for a fixed camera observing a flat board."""

    image_to_plane: Array

    @classmethod
    def from_points(cls, image_points: Array, plane_points: Array) -> "PlaneCalibrator":
        return cls(image_to_plane=estimate_homography(image_points, plane_points))

    def image_to_canvas(self, image_points: Array) -> Array:
        return apply_homography(self.image_to_plane, image_points)


def _normalize_points(points: Array) -> tuple[Array, Array]:
    center = points.mean(axis=0)
    shifted = points - center
    mean_dist = np.linalg.norm(shifted, axis=1).mean()
    if mean_dist <= 1e-12:
        raise ValueError("points are degenerate")
    scale = np.sqrt(2.0) / mean_dist
    transform = np.array(
        [
            [scale, 0.0, -scale * center[0]],
            [0.0, scale, -scale * center[1]],
            [0.0, 0.0, 1.0],
        ],
        dtype=float,
    )
    homog = np.column_stack([points, np.ones(len(points), dtype=float)])
    normalized = (transform @ homog.T).T[:, :2]
    return normalized, transform

