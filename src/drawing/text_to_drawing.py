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
    interpretation: str
    symbols: list[dict[str, str]]
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
            interpretation="这张图可以理解为稳定的三角结构：先定目标，再分步骤推进。",
            symbols=[{"name": "triangle", "meaning": "structure and focus"}],
            strokes=[triangle_points(center=(0.02, 0.0), side=0.2)],
        )
    if _has_any(lower, ["circle", "圆"]):
        return DrawingPlan(
            title="circle",
            reading="A clear circle: continuity, calm, and completion.",
            interpretation="这张图可以理解为一个闭环：今天适合收尾、复盘和把事情整理完整。",
            symbols=[{"name": "circle", "meaning": "completion and calm"}],
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
        "interpretation": plan.interpretation,
        "symbols": plan.symbols,
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
    energy = 55 + score % 41
    opportunity = 45 + ((score * 7) % 51)
    emotion = 40 + ((score * 11) % 56)
    caution = 25 + ((score * 5) % 46)

    sun_radius = 0.043 + 0.00045 * (energy - 55)
    star_size = 0.028 + 0.00035 * (opportunity - 45)
    wave_amp = 0.010 + 0.00023 * (emotion - 40)
    arrow_top = 0.035 + 0.0008 * opportunity
    caution_radius = 0.015 + 0.00018 * caution

    strokes = [
        circle_points(center=(-0.135, 0.07), radius=sun_radius, samples=96),
        circle_points(center=(-0.135, 0.07), radius=sun_radius * 0.45, samples=64),
        *_sun_rays(center=(-0.135, 0.07), radius=sun_radius + 0.018),
        star_points(center=(0.115, 0.078), outer_radius=star_size),
        star_points(center=(0.155, 0.122), outer_radius=star_size * 0.42, tips=4),
        wave_points(start=(-0.18, -0.105), width=0.36, amplitude=wave_amp, cycles=2.4),
        arc_points(center=(0.0, -0.03), radius=0.085, start_angle=3.55, end_angle=5.75),
        polyline_points([(-0.03, -0.052), (0.035, arrow_top), (0.088, 0.025)]),
        polyline_points([(0.035, arrow_top), (0.018, arrow_top - 0.032)]),
        polyline_points([(0.035, arrow_top), (0.061, arrow_top - 0.023)]),
        triangle_points(center=(-0.02, 0.022), side=0.052),
        circle_points(center=(0.165, -0.07), radius=caution_radius, samples=48),
        polyline_points([(0.165, -0.095), (0.165, -0.052)]),
    ]
    level = "偏旺" if score >= 67 else "平稳上升" if score >= 34 else "温和蓄力"
    best_window = "上午" if opportunity >= 72 else "下午" if emotion >= 70 else "傍晚前"
    action = "主动发起一次沟通" if opportunity >= 70 else "把最重要的一件事先推进一小步"
    caution_text = "别因为临时消息打乱节奏" if caution >= 50 else "注意留一点缓冲时间"
    reading = (
        f"{today.isoformat()} 今日运势：{level}。"
        f"能量 {energy}/100，机会 {opportunity}/100，情绪流动 {emotion}/100，提醒指数 {caution}/100。"
    )
    interpretation = (
        "这张运势图从左到右读：左上双层太阳代表今天的基础能量，"
        f"太阳越大表示越适合把事情摊开做，今天能量值是 {energy}/100；"
        "右上主星和小星代表外部机会，星越尖说明机会来得越突然，"
        f"今天适合在{best_window}抓住一个明确窗口；"
        "底部波浪代表情绪和沟通节奏，波幅较大时要先稳住语气再行动；"
        "中间三角形是核心任务，表示今天最好只锁定一个主目标；"
        "上升箭头是行动建议，"
        f"建议你{action}；"
        "右下圆点加竖线是提醒符号，"
        f"{caution_text}。整体解读：今天不是靠硬冲取胜，而是靠清楚选择、及时表达和稳住节奏。"
    )
    symbols = [
        {"name": "double_sun", "meaning": f"energy {energy}/100"},
        {"name": "main_star", "meaning": f"opportunity {opportunity}/100"},
        {"name": "wave", "meaning": f"emotional rhythm {emotion}/100"},
        {"name": "triangle", "meaning": "one central task"},
        {"name": "rising_arrow", "meaning": f"action: {action}"},
        {"name": "caution_mark", "meaning": caution_text},
    ]
    return DrawingPlan(
        title="today_fortune",
        reading=reading,
        interpretation=interpretation,
        symbols=symbols,
        strokes=strokes,
    )


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
        interpretation="这张抽象图可以从左到右读：圆代表整理状态，三角代表行动结构，波浪代表情绪节奏。",
        symbols=[
            {"name": "circle", "meaning": "state"},
            {"name": "triangle", "meaning": "action"},
            {"name": "wave", "meaning": "rhythm"},
        ],
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
