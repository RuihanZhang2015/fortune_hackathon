from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_SOURCE_X = (-0.23, 0.23)
DEFAULT_SOURCE_Y = (-0.17, 0.17)
DEFAULT_TARGET_X = (-130.0, 130.0)
DEFAULT_TARGET_Y = (200.0, 400.0)


def map_toolpath_payload(
    payload: dict[str, Any],
    *,
    source_x: tuple[float, float] = DEFAULT_SOURCE_X,
    source_y: tuple[float, float] = DEFAULT_SOURCE_Y,
    target_x: tuple[float, float] = DEFAULT_TARGET_X,
    target_y: tuple[float, float] = DEFAULT_TARGET_Y,
    fit: bool = False,
) -> dict[str, Any]:
    draw_z = float(payload["draw_z"])
    segments = _drawing_xy_segments(payload["points"], draw_z)
    if fit:
        source_x, source_y = _bounds_from_segments(segments)

    mapped_segments = [
        [
            [
                _map_range(point[0], source_x, target_x),
                _map_range(point[1], source_y, (target_y[1], target_y[0])),
            ]
            for point in segment
        ]
        for segment in segments
    ]
    mapped_segments = _swap_xy_segments(mapped_segments)
    mapped_points = [point for segment in mapped_segments for point in segment]

    return {
        "format": "mapped_fortune_toolpath_v1",
        "source_units": payload.get("units", "meters"),
        "target_frame": "fortune_image_xy",
        "swap_xy": True,
        "target_x_range": list(target_x),
        "target_y_range": list(target_y),
        "source_x_range": list(source_x),
        "source_y_range": list(source_y),
        "path_mode": "straight_line_segments",
        "xy_segments": mapped_segments,
        "xy_points": mapped_points,
        "point_count": len(mapped_points),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Map fortune toolpath points into image XY coordinates.")
    parser.add_argument("input", nargs="?", default="outputs/reachy_fortune/latest_fortune_toolpath.json")
    parser.add_argument("--output", "-o", default="outputs/reachy_fortune/latest_fortune_mapped.json")
    parser.add_argument("--fit", action="store_true", help="Fit the actual drawing bounds to the target coordinate box.")
    parser.add_argument("--target-x", nargs=2, type=float, default=DEFAULT_TARGET_X, metavar=("LEFT", "RIGHT"))
    parser.add_argument("--target-y", nargs=2, type=float, default=DEFAULT_TARGET_Y, metavar=("TOP", "BOTTOM"))
    args = parser.parse_args()

    input_path = Path(args.input)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    mapped = map_toolpath_payload(
        payload,
        target_x=tuple(args.target_x),
        target_y=tuple(args.target_y),
        fit=args.fit,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(mapped, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output_path}")
    print(f"segments={len(mapped['xy_segments'])} points={mapped['point_count']}")


def _drawing_xy_segments(points: list[list[float]], draw_z: float) -> list[list[list[float]]]:
    segments: list[list[list[float]]] = []
    current: list[list[float]] = []
    for point in points:
        x, y, z = point
        if float(z) <= draw_z + 1e-6:
            current.append([float(x), float(y)])
            continue
        if current:
            segments.append(current)
            current = []
    if current:
        segments.append(current)
    return segments


def _bounds_from_segments(segments: list[list[list[float]]]) -> tuple[tuple[float, float], tuple[float, float]]:
    points = [point for segment in segments for point in segment]
    if not points:
        raise ValueError("cannot fit an empty toolpath")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return _nonzero_bounds(min(xs), max(xs)), _nonzero_bounds(min(ys), max(ys))


def _swap_xy_segments(segments: list[list[list[float]]]) -> list[list[list[float]]]:
    return [[[point[1], point[0]] for point in segment] for segment in segments]


def _nonzero_bounds(low: float, high: float) -> tuple[float, float]:
    if low != high:
        return low, high
    pad = 0.001
    return low - pad, high + pad


def _map_range(value: float, source: tuple[float, float], target: tuple[float, float]) -> float:
    source_min, source_max = source
    target_min, target_max = target
    if source_min == source_max:
        raise ValueError("source range cannot be zero")
    ratio = (value - source_min) / (source_max - source_min)
    return round(target_min + ratio * (target_max - target_min), 3)


if __name__ == "__main__":
    main()
