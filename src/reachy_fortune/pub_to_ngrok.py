from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx


NGROK_URL = "https://YOUR-SUBDOMAIN.ngrok-free.app"
DEFAULT_INPUT = "outputs/reachy_fortune/latest_fortune_mapped.json"
DEFAULT_Z_MM = 200.0


def points3d_from_mapped_payload(payload: dict[str, Any], z_mm: float = DEFAULT_Z_MM) -> list[list[float]]:
    return [[float(x), float(y), float(z_mm)] for x, y in payload["xy_points"]]


def load_points3d(input_path: str | Path, z_mm: float = DEFAULT_Z_MM) -> list[list[float]]:
    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    return points3d_from_mapped_payload(payload, z_mm=z_mm)


def post(
    url: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    verbose: bool = True,
) -> httpx.Response:
    full = url.rstrip("/") + path
    response = httpx.post(full, json=payload or {}, timeout=10.0)
    if verbose:
        print(f"POST {path} -> {response.status_code} {response.text.strip()}")
    return response


def get(url: str, path: str, *, verbose: bool = True) -> httpx.Response:
    full = url.rstrip("/") + path
    response = httpx.get(full, timeout=10.0)
    if verbose:
        print(f"GET {path} -> {response.status_code} {response.text.strip()}")
    return response


def publish_trajectory(url: str, points: list[list[float]], *, verbose: bool = True) -> httpx.Response:
    return post(url, "/traj", {"points": points}, verbose=verbose)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", nargs="?", default="traj", choices=["traj", "stop", "home", "status"])
    parser.add_argument("--url", default=NGROK_URL, help="ngrok public URL of draw_from_ngrok.py")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="mapped fortune JSON to send")
    parser.add_argument("--z", type=float, default=DEFAULT_Z_MM, help="constant z value in millimeters")
    args = parser.parse_args()

    if args.url.startswith("https://YOUR-"):
        print("set NGROK_URL in this file (or pass --url ...)", file=sys.stderr)
        sys.exit(2)

    try:
        if args.action == "traj":
            points = load_points3d(args.input, z_mm=args.z)
            print(f"sending {len(points)} points from {args.input}")
            publish_trajectory(args.url, points)
        elif args.action == "stop":
            post(args.url, "/stop")
        elif args.action == "home":
            post(args.url, "/home")
        elif args.action == "status":
            get(args.url, "/status")
    except httpx.HTTPError as error:
        print(f"{args.action} failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
