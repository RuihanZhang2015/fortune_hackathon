from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from drawing.text_to_drawing import toolpath_payload_from_text

from .reachy import ReachyController
from .render import render_toolpath_png


ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = ROOT / "web" / "reachy_fortune"
OUTPUT_DIR = ROOT / "outputs" / "reachy_fortune"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime")
VOICE = os.getenv("OPENAI_REALTIME_VOICE", "marin")

app = FastAPI(title="Reachy Fortune Conversation")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

reachy = ReachyController()


class RobotDrawRequest(BaseModel):
    prompt: str = "给我分析今天的运势"
    style: str = "道教符箓、毛笔、玄妙、抽象"
    reachy_output: bool = True


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
        "output_modalities": ["audio"],
        "instructions": _instructions(),
        "audio": {
            "input": {
                "turn_detection": {"type": "semantic_vad"},
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
    prompt = f"{request.prompt}。风格：{request.style}"
    payload = toolpath_payload_from_text(prompt)
    points_xy = [[float(x), float(y)] for x, y, z in payload["points"] if z <= payload["draw_z"] + 1e-6]
    payload["robot_draw_tool_call"] = {
        "type": "robot_draw",
        "coordinate_frame": "paper_xy_meters",
        "xy_points": points_xy,
    }

    json_path = OUTPUT_DIR / "latest_fortune_toolpath.json"
    image_path = OUTPUT_DIR / "latest_fortune.png"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    render_toolpath_png(payload, image_path)

    if request.reachy_output:
        reachy.express("mystical")
    return {
        "ok": True,
        "title": payload["title"],
        "interpretation": payload["interpretation"],
        "symbols": payload["symbols"],
        "image_url": "/api/latest_render.png",
        "toolpath_url": "/api/latest_toolpath.json",
        "tool_call": payload["robot_draw_tool_call"],
        "point_count": len(points_xy),
        "reachy_output": request.reachy_output,
        "reachy_mode": reachy.mode,
    }


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


@app.post("/api/reachy/say")
def reachy_say(request: SayRequest) -> JSONResponse:
    reachy.say(request.text, emotion=request.emotion)
    return JSONResponse({"ok": True, "mode": reachy.mode})


@app.post("/api/reachy/express/{emotion}")
def reachy_express(emotion: str) -> JSONResponse:
    reachy.express(emotion)
    return JSONResponse({"ok": True, "mode": reachy.mode})


@app.get("/api/reachy/status")
def reachy_status() -> dict[str, str]:
    return {"mode": reachy.mode}


def _instructions() -> str:
    return """
你是 Reachy Mini 上的玄妙小道童助手。你用中文自然对话，语气温和、有一点神秘，但不要吓人。

当用户问“今天的运势”“运势分析”“能不能画一张运势图”等类似请求时，必须调用 robot_draw 工具。
工具返回后，你要用返回的 interpretation 作为主要回复内容，说得抽象、诗意、神神秘秘一些。

平时聊天时，简短回应，并通过情绪语气表达：开心时轻快，思考时放慢，神秘时压低一点。
不要把轨迹点全部念出来；只解释图里的元素和整体意象。
""".strip()


def _robot_draw_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "robot_draw",
        "description": "Generate a Taoist-brush-style fortune drawing as robot-drawable XY trajectory points, render it in the backend, and return a mystical interpretation.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The user's fortune drawing request.",
                },
                "style": {
                    "type": "string",
                    "description": "Requested visual style. Default: Taoist talisman brush drawing.",
                },
            },
            "required": ["prompt"],
        },
    }


def main() -> None:
    import uvicorn

    uvicorn.run("reachy_fortune.app:app", host="127.0.0.1", port=8787, reload=False)


if __name__ == "__main__":
    main()
