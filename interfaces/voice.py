"""Voice pipeline interface — async wrapper for standalone / scripting use.

The production pipeline (wake word → STT → daemon → TTS) is in:
  daemon/src/jarvis/voice/
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon" / "src"))

from jarvis.config import get_config
from jarvis.voice.stt import WhisperSTT
from jarvis.voice.tts import PiperTTS


class VoicePipeline:
    def __init__(self) -> None:
        cfg      = get_config()
        self.stt = WhisperSTT(cfg)
        self.tts = PiperTTS(cfg)

    async def listen_and_transcribe(self, duration_s: float = 5.0) -> str:
        return await self.stt.record_and_transcribe(duration_s)

    async def transcribe_file(self, path: str | Path) -> str:
        return await self.stt.transcribe_file(Path(path))

    async def transcribe_bytes(self, audio_bytes: bytes) -> str:
        return await self.stt.transcribe_bytes(audio_bytes)

    async def speak(self, text: str) -> None:
        await self.tts.speak(text)

    async def synthesize(self, text: str) -> bytes | None:
        return await self.tts.synthesize(text)


if __name__ == "__main__":
    async def _demo() -> None:
        pipeline = VoicePipeline()
        print("Recording for 5 seconds…")
        text = await pipeline.listen_and_transcribe(5.0)
        print(f"Heard: {text!r}")
        if text:
            await pipeline.speak(f"I heard: {text}")

    asyncio.run(_demo())
