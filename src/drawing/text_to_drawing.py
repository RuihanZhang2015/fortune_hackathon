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

    taiji_radius = 0.052 + 0.00022 * (energy - 55)
    seal_size = 0.042 + 0.00018 * opportunity
    wave_amp = 0.010 + 0.00023 * (emotion - 40)
    caution_radius = 0.015 + 0.00018 * caution

    strokes = [
        *_taiji_mark(center=(-0.125, 0.058), radius=taiji_radius),
        *_trigram_mark(origin=(0.075, 0.108), width=0.105, gap=0.022, broken=score % 2 == 0),
        *_talisman_mark(center=(0.02, 0.012), height=0.15, width=seal_size),
        wave_points(start=(-0.185, -0.105), width=0.37, amplitude=wave_amp, cycles=2.8),
        arc_points(center=(-0.02, -0.064), radius=0.085, start_angle=3.55, end_angle=5.85),
        circle_points(center=(0.165, -0.072), radius=caution_radius, samples=48),
        polyline_points([(0.165, -0.099), (0.165, -0.052)]),
        star_points(center=(0.145, 0.025), outer_radius=0.023, tips=4),
    ]
    level = "偏旺" if score >= 67 else "平稳上升" if score >= 34 else "温和蓄力"
    best_window = "上午" if opportunity >= 72 else "下午" if emotion >= 70 else "傍晚前"
    action = "先定心，再开口，把一个关键请求讲清楚" if opportunity >= 70 else "先收束杂念，把最重要的一件事推进一小步"
    caution_text = "避开急躁和临时起意" if caution >= 50 else "给自己留一点静气和缓冲"
    reading = (
        f"{today.isoformat()} 今日玄运：{level}。"
        f"阳气 {energy}/100，机缘 {opportunity}/100，心潮 {emotion}/100，避忌 {caution}/100。"
    )
    interpretation = (
        "这张玄运图按道教符号从左到右、由上到下解读：左侧太极印是今日阴阳底盘，"
        f"阳气值 {energy}/100，说明今天适合先稳住内在节奏，再把事情向外推进；"
        "右上三爻卦是机缘门，完整横线代表可直接把握的机会，断线代表需要绕一步再进入，"
        f"今天机缘值 {opportunity}/100，较适合在{best_window}做决定；"
        "中央符箓是行动轴，竖线定心，折笔开路，左右短横像护符的门闩，表示先收束再突破；"
        "底部云气线是心潮，波纹越明显，越提醒你说话做事要慢半拍；"
        "右下朱砂点加竖线是避忌印，提示今天不要被杂念牵走，"
        f"具体提醒是：{caution_text}。"
        f"综合来看，今天的开运法是：{action}。这不是迷信式结论，而是把你的状态翻译成一张可执行的行动图。"
    )
    symbols = [
        {"name": "taiji_seal", "meaning": f"yin-yang baseline, yang energy {energy}/100"},
        {"name": "three_line_hexagram", "meaning": f"opportunity gate {opportunity}/100"},
        {"name": "talisman_axis", "meaning": "focus first, then act"},
        {"name": "cloud_wave", "meaning": f"emotional current {emotion}/100"},
        {"name": "cinnabar_caution_dot", "meaning": caution_text},
        {"name": "guiding_star", "meaning": f"action: {action}"},
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


def _taiji_mark(center: tuple[float, float], radius: float) -> list[Stroke]:
    return [
        circle_points(center=center, radius=radius, samples=112),
        arc_points(center=(center[0], center[1] + radius / 2.0), radius=radius / 2.0,
                   start_angle=-math.pi / 2.0, end_angle=math.pi / 2.0, samples=42),
        arc_points(center=(center[0], center[1] - radius / 2.0), radius=radius / 2.0,
                   start_angle=math.pi / 2.0, end_angle=3.0 * math.pi / 2.0, samples=42),
        circle_points(center=(center[0], center[1] + radius / 2.0), radius=radius * 0.12, samples=28),
        circle_points(center=(center[0], center[1] - radius / 2.0), radius=radius * 0.12, samples=28),
    ]


def _trigram_mark(
    origin: tuple[float, float],
    width: float,
    gap: float,
    broken: bool,
) -> list[Stroke]:
    strokes = []
    y_values = [origin[1], origin[1] - gap, origin[1] - 2.0 * gap]
    for index, y in enumerate(y_values):
        should_break = broken and index == 1
        if should_break:
            strokes.append(polyline_points([(origin[0], y), (origin[0] + width * 0.38, y)]))
            strokes.append(polyline_points([(origin[0] + width * 0.62, y), (origin[0] + width, y)]))
        else:
            strokes.append(polyline_points([(origin[0], y), (origin[0] + width, y)]))
    return strokes


def _talisman_mark(center: tuple[float, float], height: float, width: float) -> list[Stroke]:
    x, y = center
    top = y + height / 2.0
    bottom = y - height / 2.0
    return [
        polyline_points([(x, top), (x, bottom)]),
        polyline_points([(x - width, top - 0.012), (x, top), (x + width, top - 0.012)]),
        polyline_points([(x - width * 0.75, top - 0.045), (x + width * 0.75, top - 0.045)]),
        polyline_points([(x - width * 0.65, y + 0.005), (x + width * 0.65, y - 0.015)]),
        polyline_points([(x + width * 0.45, y + 0.03), (x - width * 0.2, y - 0.04), (x + width * 0.55, y - 0.075)]),
        polyline_points([(x - width * 0.8, bottom + 0.018), (x, bottom), (x + width * 0.8, bottom + 0.018)]),
    ]


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
