"""
JARVIS Video Creator — 100% Free Pipeline
──────────────────────────────────────────
TTS    : edge-tts  (Microsoft Edge voices, no API key needed)
Images : Pollinations.ai  (Flux model, no API key, no sign-up)
Compose: FFmpeg  (local, free)
LLM    : existing JARVIS router (for scene breakdown)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

# ── In-memory job store ────────────────────────────────────────────────────────
jobs: dict[str, dict] = {}
# job schema: {status:str, progress:int, path:str|None, error:str|None, platform:str}

# ── Platform → (width, height) ────────────────────────────────────────────────
ASPECT: dict[str, tuple[int, int]] = {
    "youtube":  (1920, 1080),
    "shorts":   (1080, 1920),
    "tiktok":   (1080, 1920),
    "reels":    (1080, 1920),
    "facebook": (1080, 1080),
    "square":   (1080, 1080),
}

# ── Edge-TTS voice map ─────────────────────────────────────────────────────────
VOICES: dict[str, str] = {
    "en":       "en-US-AndrewNeural",      # male, natural
    "en-f":     "en-US-JennyNeural",       # female
    "bn":       "bn-BD-NabanitaNeural",    # Bengali female
    "bn-m":     "bn-BD-PradeepNeural",     # Bengali male
    "banglish": "en-US-AndrewNeural",      # Banglish → English voice
}

# ── Font search (for burned-in captions) ──────────────────────────────────────
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
]

def _find_font() -> str | None:
    for f in _FONT_CANDIDATES:
        if os.path.exists(f):
            return f
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def start_video_job(
    script: str,
    platform: str = "youtube",
    voice_key: str = "en",
    llm_complete_fn=None,
    output_dir: Path = Path("/tmp/jarvis_videos"),
) -> str:
    """
    Launch a background video creation job.
    Returns job_id immediately; poll get_job(job_id) for progress.
    llm_complete_fn: async callable(prompt: str) -> str
    """
    job_id = uuid.uuid4().hex[:10]
    jobs[job_id] = {
        "status":   "queued",
        "progress": 0,
        "path":     None,
        "error":    None,
        "platform": platform,
    }
    asyncio.ensure_future(
        _run_pipeline(job_id, script, platform, voice_key, llm_complete_fn, output_dir)
    )
    return job_id


def get_job(job_id: str) -> dict | None:
    return jobs.get(job_id)


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline
# ══════════════════════════════════════════════════════════════════════════════

async def _run_pipeline(
    job_id: str,
    script: str,
    platform: str,
    voice_key: str,
    llm_fn,
    output_dir: Path,
):
    work_dir = output_dir / job_id
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        w, h = ASPECT.get(platform.lower(), (1920, 1080))
        voice = VOICES.get(voice_key, VOICES["en"])
        font  = _find_font()

        # ── 1. Scene breakdown ─────────────────────────────────────────────
        _upd(job_id, "🧠 Analyzing script and planning scenes…", 4)
        scenes = await _parse_scenes(script, llm_fn)
        log.info("[video %s] %d scenes planned", job_id, len(scenes))

        # ── 2. Per-scene assets ────────────────────────────────────────────
        clip_paths: list[str] = []
        for i, scene in enumerate(scenes):
            base_pct = 8 + int(i / len(scenes) * 78)
            _upd(job_id, f"🎙 Scene {i+1}/{len(scenes)}: generating voiceover…", base_pct)

            audio_path = work_dir / f"s{i:03d}.mp3"
            await _gen_tts(scene["narration"], str(audio_path), voice)

            _upd(job_id, f"🖼 Scene {i+1}/{len(scenes)}: generating image…", base_pct + 2)
            img_path = work_dir / f"s{i:03d}.jpg"
            await _gen_image(scene["visual_prompt"], str(img_path), w, h, seed=i * 137 + 42)

            dur = await _audio_duration(str(audio_path))
            dur = max(dur, 3.0)  # minimum 3 seconds per scene

            _upd(job_id, f"🎞 Scene {i+1}/{len(scenes)}: composing clip…", base_pct + 4)
            clip_path = work_dir / f"clip{i:03d}.mp4"
            await _make_clip(
                str(img_path), str(audio_path), str(clip_path),
                dur, w, h, scene.get("caption", ""), font
            )
            clip_paths.append(str(clip_path))

        # ── 3. Concatenate ─────────────────────────────────────────────────
        _upd(job_id, "🎬 Assembling final video…", 90)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"jarvis_{job_id}_{platform}.mp4"
        await _concat(clip_paths, str(out_path))

        # ── 4. Done ────────────────────────────────────────────────────────
        jobs[job_id].update(status="done", progress=100, path=str(out_path))
        log.info("[video %s] ✅ done → %s", job_id, out_path)

    except Exception as exc:
        log.exception("[video %s] pipeline error", job_id)
        jobs[job_id].update(status="error", error=str(exc))

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _upd(job_id: str, msg: str, pct: int):
    if job_id in jobs:
        jobs[job_id]["status"]   = msg
        jobs[job_id]["progress"] = pct


# ══════════════════════════════════════════════════════════════════════════════
# Step 1 — Scene breakdown via LLM
# ══════════════════════════════════════════════════════════════════════════════

_SCENE_PROMPT = """\
You are a professional video director and scriptwriter.
Break the following script into video scenes for a {platform} video.

Rules:
- Each scene = 10–25 seconds of narration (split at natural sentence breaks)
- Maximum 10 scenes total
- visual_prompt: detailed Flux/Stable Diffusion image prompt (cinematic, no text in image)
- caption: 4–8 words shown on screen (the key message of this scene)
- narration: exact spoken words for this scene

Return ONLY a valid JSON array, no markdown fences, no extra text:
[
  {{
    "narration": "...",
    "visual_prompt": "...",
    "caption": "..."
  }}
]

Script:
{script}"""


async def _parse_scenes(script: str, llm_fn) -> list[dict]:
    if llm_fn is None:
        # Fallback: one scene = entire script
        return [{"narration": script, "visual_prompt": "professional studio background, dark, cinematic lighting", "caption": ""}]

    prompt = _SCENE_PROMPT.format(script=script, platform="YouTube")
    try:
        raw = await llm_fn(prompt)
        # Extract JSON array robustly
        match = re.search(r'\[[\s\S]*\]', raw)
        if not match:
            raise ValueError("No JSON array found in LLM response")
        scenes = json.loads(match.group())
        if not isinstance(scenes, list) or not scenes:
            raise ValueError("Empty scene list")
        # Validate keys
        for s in scenes:
            s.setdefault("narration", script[:200])
            s.setdefault("visual_prompt", "cinematic background, professional, dark theme")
            s.setdefault("caption", "")
        return scenes
    except Exception as e:
        log.warning("[video] scene parse failed (%s), using single-scene fallback", e)
        # Fallback: split by sentences naively
        sentences = re.split(r'(?<=[.!?])\s+', script.strip())
        chunk_size = max(1, len(sentences) // 5)
        scenes = []
        for i in range(0, len(sentences), chunk_size):
            chunk = " ".join(sentences[i:i + chunk_size])
            scenes.append({
                "narration": chunk,
                "visual_prompt": f"cinematic professional background scene {i//chunk_size+1}, dark atmosphere, high quality",
                "caption": chunk[:50] + "…" if len(chunk) > 50 else chunk,
            })
        return scenes[:10]


# ══════════════════════════════════════════════════════════════════════════════
# Step 2a — TTS via edge-tts
# ══════════════════════════════════════════════════════════════════════════════

async def _gen_tts(text: str, output_path: str, voice: str):
    """Generate speech audio using edge-tts (free, no API key)."""
    try:
        import edge_tts  # pip install edge-tts
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
        return
    except ImportError:
        log.warning("[video] edge-tts not installed, trying espeak-ng fallback")
    except Exception as e:
        log.warning("[video] edge-tts failed: %s, trying espeak-ng", e)

    # Fallback: espeak-ng → wav → mp3
    wav = output_path.replace(".mp3", ".wav")
    try:
        proc = await asyncio.create_subprocess_exec(
            "espeak-ng", "-w", wav, text,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        await _ffmpeg(["-i", wav, "-y", output_path])
        os.remove(wav)
    except FileNotFoundError:
        # Last resort: generate silent audio matching estimated duration
        words = len(text.split())
        dur = max(3.0, words / 2.5)  # ~150 wpm
        await _ffmpeg([
            "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
            "-t", str(dur), "-c:a", "libmp3lame", "-q:a", "4", "-y", output_path,
        ])


# ══════════════════════════════════════════════════════════════════════════════
# Step 2b — Image via Pollinations.ai (Flux, free, no key)
# ══════════════════════════════════════════════════════════════════════════════

async def _gen_image(prompt: str, output_path: str, w: int, h: int, seed: int = 42):
    """Download AI image from Pollinations.ai — completely free, no API key."""
    # Enhance prompt for cinematic quality
    full_prompt = f"{prompt}, cinematic, 8k, professional photography, no text, no watermark"
    encoded = urllib.parse.quote(full_prompt)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={w}&height={h}&nologo=true&seed={seed}&model=flux&enhance=true"
    )

    try:
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    with open(output_path, "wb") as f:
                        f.write(data)
                    log.debug("[video] image downloaded: %s", output_path)
                    return
                log.warning("[video] Pollinations returned %d", resp.status)
    except Exception as e:
        log.warning("[video] image download failed: %s", e)

    # Fallback: generate solid dark gradient placeholder via FFmpeg
    await _ffmpeg([
        "-f", "lavfi",
        "-i", f"color=c=0x0d0d10:s={w}x{h}:d=1",
        "-frames:v", "1", "-y", output_path,
    ])


# ══════════════════════════════════════════════════════════════════════════════
# Step 2c — Get audio duration
# ══════════════════════════════════════════════════════════════════════════════

async def _audio_duration(path: str) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    try:
        data = json.loads(out)
        return float(data["streams"][0]["duration"])
    except Exception:
        return 8.0  # safe default


# ══════════════════════════════════════════════════════════════════════════════
# Step 3 — Compose one scene clip (image + audio + caption)
# ══════════════════════════════════════════════════════════════════════════════

async def _make_clip(
    img: str, audio: str, out: str,
    dur: float, w: int, h: int,
    caption: str, font: str | None,
):
    # Scale + crop image to exact target resolution
    vf_parts = [
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h}"
    ]

    # Burn in caption (bottom third)
    if caption:
        safe = (
            caption
            .replace("\\", "\\\\")
            .replace("'",  "\\'")
            .replace(":",  "\\:")
            .replace("%",  "\\%")
        )
        font_size = max(28, w // 30)
        y_pos     = f"h-text_h-{h // 12}"
        font_arg  = f":fontfile={font}" if font else ""
        vf_parts.append(
            f"drawtext=text='{safe}'"
            f":fontcolor=white:fontsize={font_size}"
            f":box=1:boxcolor=black@0.50:boxborderw=12"
            f":x=(w-text_w)/2:y={y_pos}"
            f":enable='between(t,0.4,{dur:.1f})'"
            f"{font_arg}"
        )

    vf = ",".join(vf_parts)

    await _ffmpeg([
        "-loop", "1", "-i", img,
        "-i", audio,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-r", "25",
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-t", f"{dur + 0.4:.2f}",
        "-y", out,
    ])


# ══════════════════════════════════════════════════════════════════════════════
# Step 4 — Concatenate all clips
# ══════════════════════════════════════════════════════════════════════════════

async def _concat(clips: list[str], output: str):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for c in clips:
            f.write(f"file '{c}'\n")
        list_path = f.name

    try:
        await _ffmpeg([
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-y", output,
        ])
    finally:
        try:
            os.unlink(list_path)
        except OSError:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# FFmpeg helper
# ══════════════════════════════════════════════════════════════════════════════

async def _ffmpeg(args: list[str]):
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {stderr.decode()[-600:]}")
