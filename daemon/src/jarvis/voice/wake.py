"""Wake word listener — runs as a persistent user-space service.

Pipeline: microphone → openWakeWord model → trigger → STT → JARVIS daemon → TTS
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

import httpx
import numpy as np
import sounddevice as sd

from ..config import get_config

log  = logging.getLogger(__name__)
cfg  = get_config()

SAMPLE_RATE    = 16000
CHUNK_DURATION = 0.1          # seconds per chunk fed to wake word engine
CHUNK_FRAMES   = int(SAMPLE_RATE * CHUNK_DURATION)
RECORD_AFTER_S = 4.0          # seconds to record after wake word detected
DAEMON_URL     = f"http://{cfg.host}:{cfg.port}"


async def _transcribe_and_respond(audio: np.ndarray) -> None:
    import io, wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes((audio * 32767).astype(np.int16).tobytes())

    async with httpx.AsyncClient(timeout=60) as client:
        # 1. Transcribe
        resp = await client.post(
            f"{DAEMON_URL}/api/voice/transcribe",
            files={"audio": ("query.wav", buf.getvalue(), "audio/wav")},
        )
        resp.raise_for_status()
        text = resp.json()["text"].strip()
        if not text:
            return

        log.info("heard: %r", text)

        # 2. Stream response via WebSocket and collect full reply
        import websockets  # type: ignore
        full_reply = ""
        async with websockets.connect(f"ws://{cfg.host}:{cfg.port}/ws/chat") as ws:
            await ws.send(__import__("json").dumps({"query": text}))
            while True:
                msg = __import__("json").loads(await ws.recv())
                if msg["type"] == "chunk":
                    full_reply += msg["content"]
                elif msg["type"] == "done":
                    break

        log.info("jarvis: %r", full_reply[:80])

        # 3. Speak reply
        await client.post(f"{DAEMON_URL}/api/voice/speak", json={"text": full_reply})


async def _oww_listener() -> None:
    """openWakeWord-based listener (preferred)."""
    try:
        from openwakeword.model import Model  # type: ignore
    except ImportError:
        log.warning("openWakeWord not installed — falling back to simple energy VAD")
        await _vad_listener()
        return

    oww_model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    log.info("wake word listener active — say '%s'", cfg.wake_word)

    q: asyncio.Queue[np.ndarray] = asyncio.Queue()

    def _audio_cb(indata: np.ndarray, frames: int, t, status) -> None:
        if status:
            log.debug("audio status: %s", status)
        q.put_nowait(indata.copy())

    loop = asyncio.get_event_loop()
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        blocksize=CHUNK_FRAMES, callback=_audio_cb):
        while True:
            chunk = await q.get()
            scores = oww_model.predict(chunk.flatten())
            if scores.get("hey_jarvis", 0) > cfg.voice_threshold:
                log.info("wake word detected! recording...")
                frames_needed = int(SAMPLE_RATE * RECORD_AFTER_S)
                collected     = []
                while sum(len(c) for c in collected) < frames_needed:
                    try:
                        c = await asyncio.wait_for(q.get(), timeout=RECORD_AFTER_S)
                        collected.append(c.flatten())
                    except asyncio.TimeoutError:
                        break
                audio = np.concatenate(collected) if collected else np.zeros(frames_needed)
                asyncio.ensure_future(_transcribe_and_respond(audio))


async def _vad_listener() -> None:
    """Fallback: energy-based VAD — waits for audio above threshold."""
    ENERGY_THRESH  = 0.02
    SILENCE_THRESH = 0.8  # seconds of silence = end of utterance
    MIN_SPEECH_S   = 0.4

    log.info("VAD listener active (no wake word — all speech triggers JARVIS)")

    q: asyncio.Queue[np.ndarray] = asyncio.Queue()

    def _cb(indata: np.ndarray, frames: int, t, status) -> None:
        q.put_nowait(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        blocksize=CHUNK_FRAMES, callback=_cb):
        recording      = False
        speech_buf: list[np.ndarray] = []
        last_speech_ts = 0.0

        while True:
            chunk = await q.get()
            energy = float(np.abs(chunk).mean())

            if energy > ENERGY_THRESH:
                last_speech_ts = time.monotonic()
                if not recording:
                    recording = True
                    speech_buf.clear()
                    log.debug("speech start")
                speech_buf.append(chunk.flatten())
            elif recording:
                silence_dur = time.monotonic() - last_speech_ts
                if silence_dur > SILENCE_THRESH:
                    audio = np.concatenate(speech_buf) if speech_buf else np.zeros(CHUNK_FRAMES)
                    if len(audio) / SAMPLE_RATE >= MIN_SPEECH_S:
                        asyncio.ensure_future(_transcribe_and_respond(audio))
                    recording = False
                    speech_buf.clear()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [wake] %(levelname)s %(message)s",
    )
    asyncio.run(_oww_listener())


if __name__ == "__main__":
    main()
