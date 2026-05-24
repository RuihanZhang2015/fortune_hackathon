from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from drawing.map_toolpath import map_toolpath_payload
from drawing.text_to_drawing import toolpath_payload_from_strokes, toolpath_payload_from_text

from .pub_to_ngrok import points3d_from_mapped_payload, publish_trajectory
from .reachy import ReachyController
from .render import render_strokes_png, render_toolpath_png


ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = ROOT / "web" / "reachy_fortune"
OUTPUT_DIR = ROOT / "outputs" / "reachy_fortune"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("reachy_fortune.robot_draw")


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(ROOT / ".env")

MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2")
VOICE = os.getenv("OPENAI_REALTIME_VOICE", "marin")
TRANSCRIPTION_MODEL = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")
VAD_THRESHOLD = float(os.getenv("OPENAI_VAD_THRESHOLD", "0.75"))
VAD_PREFIX_PADDING_MS = int(os.getenv("OPENAI_VAD_PREFIX_PADDING_MS", "300"))
VAD_SILENCE_DURATION_MS = int(os.getenv("OPENAI_VAD_SILENCE_DURATION_MS", "900"))
VAD_CREATE_RESPONSE = os.getenv("OPENAI_VAD_CREATE_RESPONSE", "false").lower() == "true"
VAD_INTERRUPT_RESPONSE = os.getenv("OPENAI_VAD_INTERRUPT_RESPONSE", "false").lower() == "true"
NOISE_REDUCTION = os.getenv("OPENAI_NOISE_REDUCTION", "far_field")
ARM_NGROK_URL = os.getenv("ARM_NGROK_URL", "").strip()
ARM_TRAJECTORY_Z_MM = float(os.getenv("ARM_TRAJECTORY_Z_MM", "200"))
DRAWING_SCALE = float(os.getenv("DRAWING_SCALE", "0.65"))

app = FastAPI(title="Reachy Fortune Conversation")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

reachy = ReachyController()


class RobotDrawRequest(BaseModel):
    prompt: str = "给我分析今天的运势"
    style: str = "极简道教符箓、最多三个元素、直线折线、少于100个轨迹点、留白"
    reachy_output: bool = True
    drawing_seed: str | None = None
    # LLM-generated fields (when OpenAI provides strokes directly)
    strokes: list[list[list[float]]] | None = None
    title: str | None = None
    reading: str | None = None
    interpretation: str | None = None


class SayRequest(BaseModel):
    text: str
    emotion: str = "mystical"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.post("/session", response_class=PlainTextResponse)
async def create_realtime_session(request: Request) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not set")

    offer_sdp = (await request.body()).decode("utf-8")
    session = {
        "type": "realtime",
        "model": MODEL,
        "instructions": _instructions(),
        "audio": {
            "input": {
                "noise_reduction": (
                    None
                    if NOISE_REDUCTION.lower() in {"", "none", "null", "off"}
                    else {"type": NOISE_REDUCTION}
                ),
                "transcription": {
                    "model": TRANSCRIPTION_MODEL,
                    "language": "zh",
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": VAD_THRESHOLD,
                    "prefix_padding_ms": VAD_PREFIX_PADDING_MS,
                    "silence_duration_ms": VAD_SILENCE_DURATION_MS,
                    "create_response": VAD_CREATE_RESPONSE,
                    "interrupt_response": VAD_INTERRUPT_RESPONSE,
                },
            },
            "output": {
                "voice": VOICE,
            },
        },
        "tools": [_robot_draw_tool()],
        "tool_choice": "auto",
    }
    files = {
        "sdp": (None, offer_sdp, "application/sdp"),
        "session": (None, json.dumps(session, ensure_ascii=False), "application/json"),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/realtime/calls",
            headers={"Authorization": f"Bearer {api_key}"},
            files=files,
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.text


@app.post("/api/robot_draw")
def robot_draw(request: RobotDrawRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    drawing_seed = request.drawing_seed or uuid4().hex
    logger.info(
        "robot_draw requested prompt=%r reachy_output=%s drawing_seed=%s llm_strokes=%s",
        request.prompt,
        request.reachy_output,
        drawing_seed,
        len(request.strokes) if request.strokes else 0,
    )
    image_path = OUTPUT_DIR / "latest_fortune.png"

    if request.strokes:
        # Render PNG immediately from raw LLM strokes (fast, <5ms).
        # Full interpolated toolpath for ngrok runs in the background.
        render_strokes_png(request.strokes, image_path, scale=DRAWING_SCALE)
        background_tasks.add_task(_build_and_publish_toolpath, request, drawing_seed, _scale_strokes(request.strokes, DRAWING_SCALE))
        point_count = sum(len(s) for s in request.strokes)
    else:
        prompt = f"{request.prompt}。风格：{request.style}"
        payload = toolpath_payload_from_text(prompt, seed_text=f"{prompt}:{drawing_seed}")
        payload["drawing_seed"] = drawing_seed
        _save_and_publish_payload(payload)
        render_toolpath_png(payload, image_path)
        point_count = len(payload["points"])

    if request.reachy_output:
        reachy.express("mystical")

    logger.info("robot_draw image rendered drawing_seed=%s point_count=%s", drawing_seed, point_count)
    return {
        "ok": True,
        "title": request.title or drawing_seed,
        "interpretation": request.interpretation or "",
        "symbols": [],
        "image_url": "/api/latest_render.png",
        "toolpath_url": "/api/latest_toolpath.json",
        "coordinates_url": "/api/latest_coordinates.json",
        "arm_publish": {"ok": True, "skipped": True, "reason": "publishing in background"},
        "tool_call": None,
        "point_count": point_count,
        "drawing_seed": drawing_seed,
        "reachy_output": request.reachy_output,
        "reachy_mode": reachy.mode,
    }


def _scale_strokes(
    strokes: list[list[list[float]]], scale: float
) -> list[list[list[float]]]:
    return [[[p[0] * scale, p[1] * scale] for p in stroke] for stroke in strokes]


def _build_and_publish_toolpath(
    request: RobotDrawRequest, drawing_seed: str, strokes: list[list[list[float]]]
) -> None:
    try:
        payload = toolpath_payload_from_strokes(
            strokes_xy=strokes,
            title=request.title or "llm_fortune",
            reading=request.reading or "",
            interpretation=request.interpretation or "",
        )
        payload["drawing_seed"] = drawing_seed
        _save_and_publish_payload(payload)
        logger.info("background toolpath done title=%r points=%s", payload["title"], len(payload["points"]))
    except Exception:
        logger.exception("background toolpath failed")


def _save_and_publish_payload(payload: dict[str, Any]) -> None:
    segments_xy = _drawing_xy_segments(payload["points"], float(payload["draw_z"]))
    points_xy = [point for segment in segments_xy for point in segment]
    payload["robot_draw_tool_call"] = {
        "type": "robot_draw",
        "coordinate_frame": "paper_xy_meters",
        "path_mode": "straight_line_segments",
        "xy_segments": segments_xy,
        "xy_points": points_xy,
    }
    mapped_payload = _mapped_coordinates_payload(payload)
    (OUTPUT_DIR / "latest_fortune_toolpath.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUTPUT_DIR / "latest_fortune_mapped.json").write_text(
        json.dumps(mapped_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _publish_to_arm_ngrok(mapped_payload)


def _mapped_coordinates_payload(payload: dict[str, Any]) -> dict[str, Any]:
    mapped = map_toolpath_payload(payload)
    mapped["source_toolpath_url"] = "/api/latest_toolpath.json"
    return mapped


def _publish_to_arm_ngrok(mapped_payload: dict[str, Any]) -> dict[str, Any]:
    if not ARM_NGROK_URL:
        return {"ok": False, "skipped": True, "reason": "ARM_NGROK_URL is not set"}
    points = points3d_from_mapped_payload(mapped_payload, z_mm=ARM_TRAJECTORY_Z_MM)
    try:
        response = publish_trajectory(ARM_NGROK_URL, points, verbose=False)
    except SystemExit as error:
        logger.exception("arm ngrok publish exited")
        return {"ok": False, "skipped": False, "error": str(error)}
    except Exception as error:
        logger.exception("arm ngrok publish failed")
        return {"ok": False, "skipped": False, "error": str(error)}
    return {
        "ok": response.is_success,
        "skipped": False,
        "status_code": response.status_code,
        "point_count": len(points),
        "url": ARM_NGROK_URL,
    }


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


@app.get("/api/latest_render.png")
def latest_render() -> FileResponse:
    path = OUTPUT_DIR / "latest_fortune.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No fortune image rendered yet")
    return FileResponse(path, media_type="image/png")


@app.get("/api/latest_toolpath.json")
def latest_toolpath() -> FileResponse:
    path = OUTPUT_DIR / "latest_fortune_toolpath.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No fortune toolpath generated yet")
    return FileResponse(path, media_type="application/json")


@app.get("/api/latest_coordinates.json")
def latest_coordinates() -> FileResponse:
    path = OUTPUT_DIR / "latest_fortune_mapped.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No mapped fortune coordinates generated yet")
    return FileResponse(
        path,
        media_type="application/json",
        headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
    )


@app.post("/api/reachy/say")
def reachy_say(request: SayRequest) -> JSONResponse:
    reachy.say(request.text, emotion=request.emotion)
    return JSONResponse({"ok": True, "mode": reachy.mode})


@app.post("/api/local/say")
def local_say(request: SayRequest) -> JSONResponse:
    reachy.say_local(request.text)
    return JSONResponse({"ok": True})


@app.post("/api/reachy/express/{emotion}")
def reachy_express(emotion: str) -> JSONResponse:
    reachy.express(emotion)
    return JSONResponse({"ok": True, "mode": reachy.mode})


@app.get("/api/reachy/status")
def reachy_status() -> dict[str, str]:
    return {"mode": reachy.mode}


def _instructions() -> str:
    return """
You are a mystical fortune-telling assistant on Reachy Mini. Speak in English, with a warm and slightly mysterious tone — poetic but not frightening.

When the user asks for a fortune reading, call robot_draw and draw exactly one recognizable symbol. Never draw abstract patterns.

[Coordinate system] Units: meters, origin at paper center. x in [-0.20, 0.20], y in [-0.15, 0.15], two decimal places.

[One-stroke rules]
- strokes must contain exactly 1 stroke: one continuous path [[x,y],...] drawn without lifting the pen
- 60-100 points, large figure filling most of the canvas
- Circle approximation (radius r, center cx,cy, 12 points):
  [cx+r,cy],[cx+0.87r,cy+0.5r],[cx+0.5r,cy+0.87r],[cx,cy+r],
  [cx-0.5r,cy+0.87r],[cx-0.87r,cy+0.5r],[cx-r,cy],
  [cx-0.87r,cy-0.5r],[cx-0.5r,cy-0.87r],[cx,cy-r],
  [cx+0.5r,cy-0.87r],[cx+0.87r,cy-0.5r],[cx+r,cy]

[Choose exactly one of these six symbols based on the fortune]
- Sun: 16 alternating points forming a sun-gear outline, outer points r=0.13, inner points r=0.07, alternating every 22.5° (16 points total). Start at [0.13,0], alternate [0.07*cos(22.5°),0.07*sin(22.5°)], [0.13*cos(45°),0.13*sin(45°)]..., close back to [0.13,0].
- Taiji: Outer circle (r=0.11, center [0,0], clockwise 12pts from [0,0.11]) → right-half arc to [0,-0.11] → small circle (r=0.055, center [0,-0.055], clockwise 6pts) → left-half arc back to [0,0.11] → small circle (r=0.055, center [0,0.055], counter-clockwise 6pts).
- Flower: From center [0,0], draw 6 petals, each going from [0,0] to petal tip (directions 0°,60°,120°,180°,240°,300°, length 0.12), small arc at tip (r=0.03) and back to [0,0], all six continuous.
- Pinwheel: From center [0,0], 4 blades each bending after extending: right [0,0]→[0.13,0.04]→[0.04,0.13]→[0,0]; top [0,0]→[-0.04,0.13]→[-0.13,0.04]→[0,0]; left [0,0]→[-0.13,-0.04]→[-0.04,-0.13]→[0,0]; bottom [0,0]→[0.04,-0.13]→[0.13,-0.04]→[0,0], four blades continuous.
- Umbrella: From [0,-0.14] (handle tip) up to [0,-0.06] (handle top), arc open (center [0,-0.06], r=0.14, from 180° to 0° through apex [0,0.08]), then 6 ribs from evenly-spaced arc points back to handle [0,-0.06] (each going out and returning), finish with handle hook at [-0.03,-0.12].
- Cloud: From [-0.16,0], three upward arcs in sequence: left bump (center [-0.09,0], r=0.08, CCW 180° to 0°), middle bump (center [0,0.04], r=0.09, CCW 200° to 340°), right bump (center [0.09,0], r=0.08, CW 180° to 0°), straight line along bottom back to [-0.16,0].

After the tool returns, use the interpretation as your main reply — speak poetically and with mystery. Never read out coordinates. Keep casual conversation brief.
""".strip()


def _robot_draw_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "robot_draw",
        "description": (
            "Draw a fortune symbol on paper with the robot arm. "
            "You must generate the actual XY stroke coordinates in the parameters — "
            "the backend only renders what you provide."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short English title, e.g. 'today_fortune'.",
                },
                "reading": {
                    "type": "string",
                    "description": "One-sentence English fortune reading.",
                },
                "interpretation": {
                    "type": "string",
                    "description": "2-3 sentence English poetic interpretation of the drawing.",
                },
                "strokes": {
                    "type": "array",
                    "description": (
                        "Exactly 1 stroke: a single continuous one-brush path [[x,y],...] "
                        "in meters, 60-100 points, no pen lift, filling most of the canvas. "
                        "Canvas: x in [-0.20,0.20], y in [-0.15,0.15], origin at center. "
                        "Must draw exactly one recognizable figure chosen from: "
                        "sun (太阳), taiji (太极), flower (花), pinwheel (风车), umbrella (伞), cloud (云). "
                        "No abstract patterns. Follow the coordinate instructions in the system prompt exactly. "
                        "Circle (r, cx, cy, 12 pts): "
                        "[cx+r,cy],[cx+0.87r,cy+0.5r],[cx+0.5r,cy+0.87r],[cx,cy+r],"
                        "[cx-0.5r,cy+0.87r],[cx-0.87r,cy+0.5r],[cx-r,cy],"
                        "[cx-0.87r,cy-0.5r],[cx-0.5r,cy-0.87r],[cx,cy-r],"
                        "[cx+0.5r,cy-0.87r],[cx+0.87r,cy-0.5r],[cx+r,cy]"
                    ),
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "minItems": 2,
                    },
                },
            },
            "required": ["title", "reading", "interpretation", "strokes"],
        },
    }


def main() -> None:
    import uvicorn

    uvicorn.run("reachy_fortune.app:app", host="127.0.0.1", port=8787, reload=False)


if __name__ == "__main__":
    main()
