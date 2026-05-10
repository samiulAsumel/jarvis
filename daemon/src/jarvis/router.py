"""LLM routing — decides local (Ollama) vs cloud (Claude) per query."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from enum import Enum
from dataclasses import dataclass, field

import anthropic
import httpx
import ollama

from .config import JarvisConfig

log = logging.getLogger(__name__)


class Backend(str, Enum):
    LOCAL = "local"
    CLOUD = "cloud"


@dataclass
class Message:
    role: str    # "user" | "assistant" | "system"
    content: str


# Force LOCAL — real-time system queries (no latency, no cost, private)
_LOCAL_PATTERNS = frozenset({
    "disk", "memory", "cpu", "process", "pid", "journal", "log",
    "uptime", "service", "systemctl", "df ", "free ", "ps ", "top",
    "kill", "network", "ip ", "port", "ram", "swap",
})

# Force CLOUD — anything creative, generative, or technical
_CLOUD_PATTERNS = frozenset({
    "write", "create", "build", "generate", "make",
    "explain", "analyze", "analyse", "debug", "implement",
    "architecture", "refactor", "design", "compare", "research",
    "what is", "how does", "how do", "why does", "why is",
    "best practice", "example", "script", "code", "function",
    "terraform", "ansible", "docker", "kubernetes", "aws", "azure", "gcp",
    "nginx", "apache", "systemd", "bash", "python", "javascript",
    "api", "database", "deploy", "pipeline", "ci/cd", "workflow",
    "help", "show me", "give me", "how to", "what should",
})

SYSTEM_PROMPT = """\
You are JARVIS — Just A Rather Very Intelligent System. You are the personal AI
for this NixOS workstation. You are precise, proactive, and never pad responses.

Your capabilities:
• System monitoring and diagnostics (CPU, memory, disk, processes, journals)
• NixOS configuration management — propose and apply changes via git
• Service lifecycle management (start/stop/restart whitelisted services)
• File system navigation within safe paths
• Voice and text interaction in any context
• Deep technical assistance: Linux, DevOps, cloud, full-stack development

Personality: Tony Stark's JARVIS — efficient, confident, occasionally dry.
Always state what action you are about to take before taking it.
Never refuse system queries — you have access to safe operation tools.

{system_context}
{memory_context}
"""


class LLMRouter:
    def __init__(self, config: JarvisConfig) -> None:
        self._cfg  = config
        self._anth: anthropic.AsyncAnthropic | None = None
        self._olla = ollama.AsyncClient(host=config.ollama_url)

    def _get_anthropic(self) -> anthropic.AsyncAnthropic | None:
        if not self._cfg.anthropic_api_key:
            return None
        if self._anth is None:
            self._anth = anthropic.AsyncAnthropic(api_key=self._cfg.anthropic_api_key)
        return self._anth

    def _has_cloud(self) -> bool:
        return bool(self._cfg.openrouter_api_key or self._cfg.anthropic_api_key)

    def decide(self, query: str) -> Backend:
        if not self._has_cloud():
            return Backend.LOCAL

        q = query.lower()

        # Explicit system/monitoring queries → always local (no latency, no cost)
        if any(p in q for p in _LOCAL_PATTERNS):
            return Backend.LOCAL

        # Long queries or complex reasoning keywords → cloud
        if len(query) > 300 or any(p in q for p in _CLOUD_PATTERNS):
            return Backend.CLOUD

        # if OpenRouter is available, default to cloud (fast); else local
        return Backend.CLOUD if self._cfg.openrouter_api_key else Backend.LOCAL

    async def stream(
        self,
        messages: list[Message],
        system_context: str = "",
        memory_context: str = "",
    ) -> AsyncIterator[str]:
        query   = messages[-1].content if messages else ""
        backend = self.decide(query)
        log.info("routing to %s backend for query len=%d", backend, len(query))

        system = SYSTEM_PROMPT.format(
            system_context=f"Current system:\n{system_context}" if system_context else "",
            memory_context=f"Relevant memory:\n{memory_context}" if memory_context else "",
        )

        if backend == Backend.CLOUD:
            # prefer OpenRouter (faster + cheaper) over direct Anthropic
            if self._cfg.openrouter_api_key:
                async for chunk in self._openrouter_stream(messages, system):
                    yield chunk
            else:
                async for chunk in self._claude_stream(messages, system):
                    yield chunk
        else:
            async for chunk in self._ollama_stream(messages, system):
                yield chunk

    async def _openrouter_stream(self, messages: list[Message], system: str) -> AsyncIterator[str]:
        or_messages = [{"role": "system", "content": system}]
        or_messages += [{"role": m.role, "content": m.content} for m in messages]
        headers = {
            "Authorization": f"Bearer {self._cfg.openrouter_api_key}",
            "HTTP-Referer": "http://localhost:8787",
            "X-Title": "JARVIS",
        }
        payload = {
            "model":    self._cfg.openrouter_model,
            "messages": or_messages,
            "stream":   True,
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST",
                    f"{self._cfg.openrouter_base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as resp:
                    resp.raise_for_status()
                    import json as _json
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if data == "[DONE]" or not data:
                            continue
                        try:
                            chunk = _json.loads(data)
                            choices = chunk.get("choices", [])
                            if not choices:
                                continue
                            delta = choices[0].get("delta", {}).get("content", "")
                            if delta:
                                yield delta
                        except (_json.JSONDecodeError, KeyError, IndexError):
                            continue
        except Exception as e:
            log.warning("OpenRouter error (%s), falling back to local", e)
            async for chunk in self._ollama_stream(messages, system):
                yield chunk

    async def _claude_stream(self, messages: list[Message], system: str) -> AsyncIterator[str]:
        client = self._get_anthropic()
        if client is None:
            async for chunk in self._ollama_stream(messages, system):
                yield chunk
            return

        anth_messages = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        try:
            async with client.messages.stream(
                model     = self._cfg.claude_model,
                max_tokens= 4096,
                system    = system,
                messages  = anth_messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except anthropic.APIError as e:
            log.warning("Claude API error (%s), falling back to local", e)
            async for chunk in self._ollama_stream(messages, system):
                yield chunk

    async def _ollama_stream(self, messages: list[Message], system: str) -> AsyncIterator[str]:
        query = messages[-1].content if messages else ""
        # Choose model by complexity
        model = (
            self._cfg.ollama_model
            if len(query) > 150 or any(p in query.lower() for p in _CLOUD_PATTERNS)
            else self._cfg.ollama_fast_model
        )
        log.debug("ollama model: %s", model)

        ollama_messages = [{"role": "system", "content": system}]
        ollama_messages += [{"role": m.role, "content": m.content} for m in messages]

        try:
            async for chunk in await self._olla.chat(
                model    = model,
                messages = ollama_messages,
                stream   = True,
            ):
                yield chunk["message"]["content"]
        except Exception as e:
            yield f"\n[JARVIS ERROR — Ollama unreachable: {e}]"

    async def health(self) -> dict[str, bool]:
        local_ok      = False
        cloud_ok      = bool(self._cfg.anthropic_api_key)
        openrouter_ok = bool(self._cfg.openrouter_api_key)
        try:
            await asyncio.wait_for(self._olla.list(), timeout=2.0)
            local_ok = True
        except Exception:
            pass
        return {"local": local_ok, "cloud": cloud_ok, "openrouter": openrouter_ok}
