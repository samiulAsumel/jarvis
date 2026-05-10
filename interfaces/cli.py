"""Programmatic HTTP client for the JARVIS daemon.

For the full interactive CLI use the `jarvis` binary (daemon/src/jarvis/cli.py).
This module is for scripting and programmatic access.

Usage:
    from interfaces.cli import JarvisClient

    with JarvisClient() as j:
        print(j.chat("What is my disk usage?"))
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon" / "src"))

try:
    from jarvis.config import get_config as _get_config
    _cfg = _get_config()
    _DEFAULT_URL = f"http://{_cfg.host}:{_cfg.port}"
except Exception:
    _DEFAULT_URL = "http://127.0.0.1:8787"


class JarvisClient:
    def __init__(self, base_url: str = _DEFAULT_URL, timeout: float = 600) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout)

    # ── Chat ───────────────────────────────────────────────────────────────────

    def chat(self, query: str, history: list[dict] | None = None) -> str:
        resp = self._http.post("/api/chat", json={"query": query, "history": history or []})
        resp.raise_for_status()
        return resp.json()["reply"]

    # ── Voice ──────────────────────────────────────────────────────────────────

    def speak(self, text: str) -> None:
        self._http.post("/api/voice/speak", json={"text": text}).raise_for_status()

    def transcribe(self, wav_bytes: bytes, filename: str = "audio.wav") -> str:
        resp = self._http.post(
            "/api/voice/transcribe",
            files={"audio": (filename, wav_bytes, "audio/wav")},
        )
        resp.raise_for_status()
        return resp.json()["text"]

    # ── System ─────────────────────────────────────────────────────────────────

    def system_context(self) -> str:
        return self._http.get("/api/system/context").json()["context"]

    def health(self) -> dict:
        return self._http.get("/health").json()

    def agent(self, op: str, **kwargs) -> dict:
        resp = self._http.post("/api/agent", json={"op": op, "kwargs": kwargs})
        resp.raise_for_status()
        return resp.json()

    # ── Memory ─────────────────────────────────────────────────────────────────

    def memory_search(self, query: str, n: int = 5) -> list[dict]:
        return self._http.get("/api/memory/search", params={"q": query, "n": n}).json()["entries"]

    def memory_recent(self, limit: int = 20) -> list[dict]:
        return self._http.get("/api/memory/recent", params={"limit": limit}).json()["entries"]

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "JarvisClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) or "Hello, JARVIS."
    with JarvisClient() as client:
        try:
            print(client.chat(query))
        except httpx.ConnectError:
            print("Daemon offline — run: systemctl start jarvis-daemon", file=sys.stderr)
            sys.exit(1)
