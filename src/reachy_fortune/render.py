from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def render_strokes_png(strokes_xy: list[list[list[float]]], output_path: str | Path, scale: float = 1.0) -> None:
    fig, ax = plt.subplots(figsize=(5, 5), facecolor="#f4ebd6")
    ax.set_facecolor("#f4ebd6")
    ax.set_xlim(-0.23, 0.23)
    ax.set_ylim(-0.17, 0.17)
    ax.set_aspect("equal")
    ax.axis("off")
    for stroke in strokes_xy:
        if len(stroke) < 2:
            continue
        xs = [p[0] * scale for p in stroke]
        ys = [p[1] * scale for p in stroke]
        ax.plot(xs, ys, color="#221c14", linewidth=2, solid_capstyle="round", solid_joinstyle="round")
    for spine in ax.spines.values():
        spine.set_visible(False)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="#f4ebd6")
    plt.close(fig)


def render_toolpath_png(payload: dict[str, Any], output_path: str | Path) -> None:
    draw_z = float(payload["draw_z"])
    points = payload["points"]
    strokes: list[list[list[float]]] = []
    current: list[list[float]] = []
    for point in points:
        x, y, z = point
        if float(z) <= draw_z + 1e-6:
            current.append([float(x), float(y)])
        elif current:
            strokes.append(current)
            current = []
    if current:
        strokes.append(current)
    render_strokes_png(strokes, output_path)
