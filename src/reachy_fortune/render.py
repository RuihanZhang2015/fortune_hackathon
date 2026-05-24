from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


def render_toolpath_png(payload: dict[str, Any], output_path: str | Path, size: int = 900) -> None:
    points = payload["points"]
    draw_z = float(payload["draw_z"])
    image = Image.new("RGB", (size, size), (244, 235, 214))
    draw = ImageDraw.Draw(image)

    margin = 90
    scale = min((size - 2 * margin) / 0.46, (size - 2 * margin) / 0.34)
    cx = size / 2
    cy = size / 2

    def project(point: list[float]) -> tuple[int, int]:
        x, y = point[:2]
        return int(cx + x * scale), int(cy - y * scale)

    if len(points) > 1:
        for prev_point, point in zip(points[:-1], points[1:]):
            prev_is_drawing = float(prev_point[2]) <= draw_z + 1e-6
            curr_is_drawing = float(point[2]) <= draw_z + 1e-6
            if not (prev_is_drawing and curr_is_drawing):
                continue
            prev = project(prev_point)
            curr = project(point)
            draw.line([prev, curr], fill=(34, 28, 20), width=4)

    # A subtle paper border.
    draw.rectangle([margin - 20, margin - 20, size - margin + 20, size - margin + 20], outline=(190, 164, 122), width=2)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
