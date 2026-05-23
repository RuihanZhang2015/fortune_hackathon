from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .shapes import (
    Stroke,
    arc_points,
    circle_points,
    polyline_points,
    star_points,
    triangle_points,
    wave_points,
)


@dataclass(frozen=True)
class DrawingPlan:
    """A semantic plan before it is compiled to robot tool targets."""

    title: str
    reading: str
    strokes: list[Stroke]


def plan_from_text(prompt: str, today: date | None = None) -> DrawingPlan:
    """Turn natural language into a deterministic drawing plan.

    This is intentionally local and hackathon-friendly: no API key is needed.
    The same prompt on the same date produces the same picture.
    """
    current_day = today or date.today()
    text = prompt.strip()
    lower = text.lower()
    seed = _stable_seed(f"{current_day.isoformat()}:{text}")
    score = seed % 100

    if _has_any(lower, ["fortune", "运势", "星座", "占卜", "好运", "today"]):
        return _fortune_plan(score, current_day)
    if _has_any(lower, ["triangle", "三角"]):
        return DrawingPlan(
            title="triangle",
            reading="A steady triangle: focus, structure, and forward motion.",
            strokes=[triangle_points(center=(0.02, 0.0), side=0.2)],
        )
    if _has_any(lower, ["circle", "圆"]):
        return DrawingPlan(
            title="circle",
            reading="A clear circle: continuity, calm, and completion.",
            strokes=[circle_points(center=(0.0, 0.0), radius=0.1)],
        )

    return _abstract_plan(score)


def toolpath_payload_from_text(
    prompt: str,
    draw_z: float = 0.018,
    travel_z: float = 0.09,
    spacing: float = 0.005,
    today: date | None = None,
) -> dict:
    """Compile natural language into a robot-parseable trajectory payload."""
    plan = plan_from_text(prompt, today=today)
    strokes = [stroke.with_lift(draw_z=draw_z, travel_z=travel_z) for stroke in plan.strokes]
    path = _interpolate_strokes(strokes, spacing=spacing)
    return {
        "format": "piper_toolpath_v1",
        "units": "meters",
        "frame": "canvas",
        "draw_z": draw_z,
        "travel_z": travel_z,
        "title": plan.title,
        "reading": plan.reading,
        "points": np.round(path, 6).tolist(),
    }


def write_toolpath_json(payload: dict, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def strokes_from_payload(payload: dict) -> list[np.ndarray]:
    """Read a robot payload back into simulator strokes."""
    points = np.asarray(payload["points"], dtype=float)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("payload points must be shaped (N, 3)")
    return [points]


def _fortune_plan(score: int, today: date) -> DrawingPlan:
    # Keep it compact enough for the arm while still looking intentional.
    sun_radius = 0.055 + 0.00035 * (score % 35)
    star_size = 0.032 + 0.00025 * ((score // 3) % 28)
    wave_amp = 0.012 + 0.0002 * (score % 30)
    arrow_top = 0.075 + 0.00035 * score

    strokes = [
        circle_points(center=(-0.12, 0.055), radius=sun_radius, samples=96),
        *_sun_rays(center=(-0.12, 0.055), radius=sun_radius + 0.022),
        star_points(center=(0.115, 0.075), outer_radius=star_size),
        wave_points(start=(-0.17, -0.105), width=0.34, amplitude=wave_amp, cycles=2.2),
        polyline_points([(-0.015, -0.045), (0.035, arrow_top), (0.075, 0.02)]),
        arc_points(center=(0.015, -0.015), radius=0.075, start_angle=3.55, end_angle=5.75),
    ]
    level = "high" if score >= 67 else "steady" if score >= 34 else "gentle"
    reading = (
        f"{today.isoformat()} fortune: {level} momentum. "
        "The sun is energy, the star is luck, the wave is emotion, "
        "and the rising line is the action to take."
    )
    return DrawingPlan(title="today_fortune", reading=reading, strokes=strokes)


def _abstract_plan(score: int) -> DrawingPlan:
    radius = 0.07 + 0.0004 * (score % 40)
    strokes = [
        circle_points(center=(-0.07, 0.02), radius=radius, samples=96),
        triangle_points(center=(0.095, -0.005), side=0.15),
        wave_points(start=(-0.16, -0.1), width=0.32, amplitude=0.018, cycles=1.7),
    ]
    return DrawingPlan(
        title="abstract_response",
        reading="An abstract response: balance, motion, and a simple next step.",
        strokes=strokes,
    )


def _sun_rays(center: tuple[float, float], radius: float) -> list[Stroke]:
    rays = []
    for angle in np.linspace(0.0, 2.0 * math.pi, 8, endpoint=False):
        inner = (center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle))
        outer = (
            center[0] + (radius + 0.026) * math.cos(angle),
            center[1] + (radius + 0.026) * math.sin(angle),
        )
        rays.append(polyline_points([inner, outer]))
    return rays


def _interpolate_strokes(strokes: list[np.ndarray], spacing: float) -> np.ndarray:
    from .shapes import interpolate_polyline

    if not strokes:
        return np.zeros((0, 3), dtype=float)
    return interpolate_polyline(np.vstack(strokes), spacing=spacing)


def _stable_seed(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _has_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)
