"""Text-to-speech using Piper (neural, offline, low-latency)."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path

from ..config import JarvisConfig

log = logging.getLogger(__name__)


class PiperTTS:
    def __init__(self, config: JarvisConfig) -> None:
        self._cfg    = config
        self._binary = config.piper_binary
        self._voice  = config.piper_voice
        self._model_dir = config.piper_model_dir

    async def speak(self, text: str) -> None:
        wav = await self.synthesize(text)
        if wav:
            await self._play(wav)

    async def synthesize(self, text: str) -> bytes | None:
        if not self._binary.exists():
            log.warning("piper binary not found at %s", self._binary)
            await self._espeak_fallback(text)
            return None

        model_path = self._model_dir / f"{self._voice}.onnx"
        if not model_path.exists():
            await self._download_voice()

        proc = await asyncio.create_subprocess_exec(
            str(self._binary),
            "--model", str(model_path),
            "--output-raw",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(
            proc.communicate(input=text.encode()), timeout=15
        )
        return stdout  # raw PCM 16-bit 22050Hz

    async def _play(self, pcm_bytes: bytes) -> None:
        # aplay handles raw PCM; works even without PulseAudio
        proc = await asyncio.create_subprocess_exec(
            "aplay", "--rate=22050", "--format=S16_LE", "--channels=1",
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(input=pcm_bytes), timeout=30)

    async def _download_voice(self) -> None:
        self._model_dir.mkdir(parents=True, exist_ok=True)
        # Piper voices at: https://github.com/rhasspy/piper/releases
        log.warning(
            "Piper voice '%s' not found. Download from: "
            "https://github.com/rhasspy/piper/releases and place in %s",
            self._voice, self._model_dir,
        )

    async def _espeak_fallback(self, text: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "espeak-ng", "-v", "en", text,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except FileNotFoundError:
            log.error("no TTS available — install piper or espeak-ng")
