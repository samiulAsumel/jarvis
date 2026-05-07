"""Speech-to-text using whisper.cpp binary (fast, local, offline)."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import sounddevice as sd

from ..config import JarvisConfig

log = logging.getLogger(__name__)

SAMPLE_RATE  = 16000
CHANNELS     = 1
DTYPE        = "int16"


class WhisperSTT:
    def __init__(self, config: JarvisConfig) -> None:
        self._cfg    = config
        self._binary = config.whisper_binary
        self._model  = config.whisper_model

    async def transcribe_file(self, wav_path: Path) -> str:
        if not self._binary.exists():
            return await self._python_whisper_fallback(wav_path)

        proc = await asyncio.create_subprocess_exec(
            str(self._binary),
            "-m", f"models/ggml-{self._model}.bin",
            "-f", str(wav_path),
            "--no-timestamps",
            "--language", "en",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        text = stdout.decode().strip()
        # whisper.cpp wraps output in [BLANK_AUDIO] or plain text
        return text.replace("[BLANK_AUDIO]", "").strip()

    async def transcribe_bytes(self, audio_bytes: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            wav_path = Path(f.name)
        try:
            return await self.transcribe_file(wav_path)
        finally:
            wav_path.unlink(missing_ok=True)

    async def record_and_transcribe(self, duration_s: float = 5.0) -> str:
        log.info("recording %.1fs of audio...", duration_s)
        frames = int(SAMPLE_RATE * duration_s)
        audio  = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: sd.rec(frames, samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE),
        )
        sd.wait()
        return await self._transcribe_array(audio)

    async def _transcribe_array(self, audio: np.ndarray) -> str:
        import wave, io
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # int16
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
        return await self.transcribe_bytes(buf.getvalue())

    async def _python_whisper_fallback(self, wav_path: Path) -> str:
        try:
            import whisper  # type: ignore
            model  = whisper.load_model(self._model)
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: model.transcribe(str(wav_path), language="en")
            )
            return result["text"].strip()
        except ImportError:
            log.error("neither whisper.cpp binary nor openai-whisper pip package found")
            return ""
