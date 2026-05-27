"""JARVIS daemon — FastAPI entry point. Run via: python -m jarvis.main"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import Op, SystemAgent
from .config import get_config
from .memory import JarvisMemory
from .router import LLMRouter, Message
from .video import get_job, start_video_job
from .voice.stt import WhisperSTT
from .voice.tts import PiperTTS

log = logging.getLogger(__name__)
cfg = get_config()

memory = JarvisMemory(cfg)
router = LLMRouter(cfg)
agent  = SystemAgent(cfg)
stt    = WhisperSTT(cfg)
tts    = PiperTTS(cfg)


@asynccontextmanager
async def lifespan(app: FastAPI):
    memory.initialize()
    log.info("JARVIS daemon online — http://%s:%d", cfg.host, cfg.port)
    yield
    memory.close()
    log.info("JARVIS daemon offline")


app = FastAPI(title="JARVIS", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # web UI may be opened from file:// or any local port
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static web UI ──────────────────────────────────────────────────────────

_WEB_DIR = Path(__file__).parents[3] / "web"  # jarvis-os/web/

if _WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_WEB_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def web_ui():
        index = _WEB_DIR / "index.html"
        return FileResponse(str(index))



# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    query:   str
    history: list[dict] = []


class SpeakRequest(BaseModel):
    text: str


class AgentRequest(BaseModel):
    op:     str
    kwargs: dict = {}


class VideoRequest(BaseModel):
    script:   str
    platform: str = "youtube"   # youtube | tiktok | reels | shorts | facebook
    voice:    str = "en"        # en | en-f | bn | bn-m | banglish


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    llm = await router.health()
    return {"status": "ok", "llm": llm}


# ── Chat (REST) ────────────────────────────────────────────────────────────────

@app.post("/api/chat")
async def chat(req: ChatRequest):
    sys_ctx = await agent.get_context_string()
    mem_ctx = memory.build_context_string(req.query)
    history = [Message(role=m["role"], content=m["content"]) for m in req.history]
    history.append(Message(role="user", content=req.query))

    chunks: list[str] = []
    async for chunk in router.stream(history, system_context=sys_ctx, memory_context=mem_ctx):
        chunks.append(chunk)

    reply = "".join(chunks)
    memory.store_interaction("user",      req.query)
    memory.store_interaction("assistant", reply)
    return {"reply": reply}


# ── Voice ──────────────────────────────────────────────────────────────────────

@app.post("/api/voice/transcribe")
async def transcribe(audio: UploadFile):
    data = await audio.read()
    text = await stt.transcribe_bytes(data)
    return {"text": text}


@app.post("/api/voice/speak")
async def speak(req: SpeakRequest):
    asyncio.ensure_future(tts.speak(req.text))
    return {"status": "speaking"}


# ── System ─────────────────────────────────────────────────────────────────────

@app.get("/api/system/context")
async def system_context():
    return {"context": await agent.get_context_string()}


@app.post("/api/agent")
async def run_agent(req: AgentRequest):
    try:
        op = Op(req.op)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown op: {req.op!r}")
    result = await agent.execute(op, **req.kwargs)
    return {"success": result.success, "output": result.output, "error": result.error}


# ── Memory ─────────────────────────────────────────────────────────────────────

@app.get("/api/memory/recent")
async def memory_recent(limit: int = 20):
    entries = memory.get_recent(limit=limit)
    return {
        "entries": [
            {"id": e.id, "content": e.content, "metadata": e.metadata, "timestamp": e.timestamp}
            for e in entries
        ]
    }


@app.get("/api/memory/search")
async def memory_search(q: str, n: int = 5):
    entries = memory.search(q, n=n)
    return {
        "entries": [
            {"id": e.id, "content": e.content, "distance": e.distance, "timestamp": e.timestamp}
            for e in entries
        ]
    }


# ── Video creation ─────────────────────────────────────────────────────────────

_VIDEO_OUTPUT = Path.home() / ".local/share/jarvis/videos"


def _llm_complete(router_: LLMRouter):
    """Wrap router.stream into an async complete() for the video pipeline."""
    async def _complete(prompt: str) -> str:
        chunks: list[str] = []
        async for chunk in router_.stream(
            [Message(role="user", content=prompt)],
            system_context="You are a professional video scriptwriter. Follow instructions exactly.",
        ):
            chunks.append(chunk)
        return "".join(chunks)
    return _complete


@app.post("/api/video/create")
async def video_create(req: VideoRequest):
    if not req.script.strip():
        raise HTTPException(status_code=400, detail="Script cannot be empty")
    job_id = start_video_job(
        script=req.script,
        platform=req.platform,
        voice_key=req.voice,
        llm_complete_fn=_llm_complete(router),
        output_dir=_VIDEO_OUTPUT,
    )
    return {"job_id": job_id}


@app.get("/api/video/status/{job_id}")
async def video_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/video/download/{job_id}")
async def video_download(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "done" or not job.get("path"):
        raise HTTPException(status_code=400, detail="Video not ready yet")
    path = Path(job["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Video file missing")
    return FileResponse(
        str(path),
        media_type="video/mp4",
        filename=path.name,
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


# ── WebSocket streaming chat ───────────────────────────────────────────────────

@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            data  = json.loads(await ws.receive_text())
            query = data.get("query", "").strip()
            if not query:
                continue

            sys_ctx = await agent.get_context_string()
            mem_ctx = memory.build_context_string(query)
            history = [Message(role=m["role"], content=m["content"]) for m in data.get("history", [])]
            history.append(Message(role="user", content=query))

            memory.store_interaction("user", query)
            reply_parts: list[str] = []

            async for chunk in router.stream(history, system_context=sys_ctx, memory_context=mem_ctx):
                reply_parts.append(chunk)
                await ws.send_text(json.dumps({"type": "chunk", "content": chunk}))

            reply = "".join(reply_parts)
            memory.store_interaction("assistant", reply)
            await ws.send_text(json.dumps({"type": "done", "content": reply}))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.exception("ws_chat error")
        try:
            await ws.send_text(json.dumps({"type": "error", "content": str(e)}))
        except Exception:
            pass


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s [jarvis] %(levelname)s %(name)s — %(message)s",
    )
    uvicorn.run(
        "jarvis.main:app",
        host=cfg.host,
        port=cfg.port,
        log_level=cfg.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
