from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from drawing.map_toolpath import map_toolpath_payload
from drawing.text_to_drawing import toolpath_payload_from_strokes, toolpath_payload_from_text

from .pub_to_ngrok import points3d_from_mapped_payload, publish_trajectory
from .reachy import ReachyController
from .render import render_toolpath_png


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
def robot_draw(request: RobotDrawRequest) -> dict[str, Any]:
    drawing_seed = request.drawing_seed or uuid4().hex
    logger.info(
        "robot_draw requested prompt=%r reachy_output=%s drawing_seed=%s llm_strokes=%s",
        request.prompt,
        request.reachy_output,
        drawing_seed,
        len(request.strokes) if request.strokes else 0,
    )
    if request.strokes:
        payload = toolpath_payload_from_strokes(
            strokes_xy=request.strokes,
            title=request.title or "llm_fortune",
            reading=request.reading or "",
            interpretation=request.interpretation or "",
        )
    else:
        prompt = f"{request.prompt}。风格：{request.style}"
        payload = toolpath_payload_from_text(prompt, seed_text=f"{prompt}:{drawing_seed}")
    payload["drawing_seed"] = drawing_seed
    segments_xy = _drawing_xy_segments(payload["points"], float(payload["draw_z"]))
    points_xy = [point for segment in segments_xy for point in segment]
    payload["robot_draw_tool_call"] = {
        "type": "robot_draw",
        "coordinate_frame": "paper_xy_meters",
        "path_mode": "straight_line_segments",
        "xy_segments": segments_xy,
        "xy_points": points_xy,
    }

    json_path = OUTPUT_DIR / "latest_fortune_toolpath.json"
    mapped_json_path = OUTPUT_DIR / "latest_fortune_mapped.json"
    image_path = OUTPUT_DIR / "latest_fortune.png"
    mapped_payload = _mapped_coordinates_payload(payload)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mapped_json_path.write_text(json.dumps(mapped_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    render_toolpath_png(payload, image_path)
    publish_result = _publish_to_arm_ngrok(mapped_payload)

    logger.info(
        "robot_draw generated title=%r point_count=%s image_path=%s",
        payload["title"],
        len(points_xy),
        image_path,
    )

    if request.reachy_output:
        reachy.express("mystical")
    return {
        "ok": True,
        "title": payload["title"],
        "interpretation": payload["interpretation"],
        "symbols": payload["symbols"],
        "image_url": "/api/latest_render.png",
        "toolpath_url": "/api/latest_toolpath.json",
        "coordinates_url": "/api/latest_coordinates.json",
        "arm_publish": publish_result,
        "tool_call": payload["robot_draw_tool_call"],
        "point_count": len(points_xy),
        "drawing_seed": drawing_seed,
        "reachy_output": request.reachy_output,
        "reachy_mode": reachy.mode,
    }


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
你是 Reachy Mini 上的玄妙小道童助手。用中文自然对话，语气温和、略带神秘，但不要吓人。

当用户请求运势图时，调用 robot_draw，从下面六个图案中选一个来画，必须画得认得出，绝不画抽象符号。

【坐标系】单位：米，纸张中心为原点。x in [-0.20, 0.20]，y in [-0.15, 0.15]，保留两位小数。

【一笔画规则】
- strokes 里只放一条笔划，一笔连续画完整个图案，不抬笔
- 60~100 个点，图案要大，撑满画布大部分空间
- 圆弧近似（半径 r，圆心 cx,cy，12 点）：
  [cx+r,cy],[cx+0.87r,cy+0.5r],[cx+0.5r,cy+0.87r],[cx,cy+r],
  [cx-0.5r,cy+0.87r],[cx-0.87r,cy+0.5r],[cx-r,cy],
  [cx-0.87r,cy-0.5r],[cx-0.5r,cy-0.87r],[cx,cy-r],
  [cx+0.5r,cy-0.87r],[cx+0.87r,cy-0.5r],[cx+r,cy]

【必须从这六个中选一个，根据运势判断哪个最合适】
- 太阳：16个交替点形成太阳齿轮轮廓，外圈点r=0.13，内圈点r=0.07，每22.5°交替一个点（共16点），从[0.13,0]出发，依次[0.07×cos22.5°,0.07×sin22.5°],[0.13×cos45°,0.13×sin45°]...，最后连回[0.13,0]，形成八角太阳
- 太极：外大圆（r=0.11，圆心[0,0]，顺时针12点从[0,0.11]开始）→ 沿右半大圆弧到[0,-0.11] → 下小圆（r=0.055，圆心[0,-0.055]，顺时针6点）→ 沿左半大圆弧到[0,0.11] → 上小圆（r=0.055，圆心[0,0.055]，逆时针6点），一笔画出太极轮廓
- 花：从圆心[0,0]出发，画6片花瓣，每片从[0,0]出发到花瓣顶端（依次方向0°,60°,120°,180°,240°,300°，每瓣长0.12），顶端做小圆弧（r=0.03）再回[0,0]，六片连续
- 风车：从圆心[0,0]出发，画4片叶片，每片从圆心延伸后弯折：右叶[0,0]→[0.13,0.04]→[0.04,0.13]→[0,0]；上叶[0,0]→[-0.04,0.13]→[-0.13,0.04]→[0,0]；左叶[0,0]→[-0.13,-0.04]→[-0.04,-0.13]→[0,0]；下叶[0,0]→[0.04,-0.13]→[0.13,-0.04]→[0,0]，四片连续
- 伞：从[0,-0.14]（伞柄底）向上到[0,-0.06]（伞柄顶），展开圆弧（圆心[0,-0.06]，r=0.14，从180°到0°经过顶点[0,0.08]），再从圆弧均匀位置画6条伞骨直线到伞柄[0,-0.06]（每骨出去再折回），最后伞柄弯钩[-0.03,-0.12]
- 云：从[-0.16,0]出发，连续三个上凸圆弧：左泡（圆心[-0.09,0]，r=0.08，从180°逆时针到0°），中泡（圆心[0,0.04]，r=0.09，从200°逆时针到340°），右泡（圆心[0.09,0]，r=0.08，从180°顺时针到0°），底部直线连回[-0.16,0]

工具返回后，用 interpretation 作主要回复，说得抽象诗意。不要念坐标。平时聊天简短回应。
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
                    "description": "One-sentence Chinese fortune reading.",
                },
                "interpretation": {
                    "type": "string",
                    "description": "2-3 sentence Chinese poetic interpretation of the drawing.",
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
