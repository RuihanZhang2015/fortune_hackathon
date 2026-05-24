from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


def render_toolpath_png(payload: dict[str, Any], output_path: str | Path, size: int = 900) -> None:
    points = payload["robot_draw_tool_call"]["xy_points"]
    image = Image.new("RGB", (size, size), (244, 235, 214))
    draw = ImageDraw.Draw(image)

    margin = 90
    scale = min((size - 2 * margin) / 0.46, (size - 2 * margin) / 0.34)
    cx = size / 2
    cy = size / 2

    def project(point: list[float]) -> tuple[int, int]:
        x, y = point
        return int(cx + x * scale), int(cy - y * scale)

    if len(points) > 1:
        prev = project(points[0])
        for point in points[1:]:
            curr = project(point)
            if abs(curr[0] - prev[0]) + abs(curr[1] - prev[1]) < 90:
                draw.line([prev, curr], fill=(34, 28, 20), width=4)
            prev = curr

    # A subtle paper border.
    draw.rectangle([margin - 20, margin - 20, size - margin + 20, size - margin + 20], outline=(190, 164, 122), width=2)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)

