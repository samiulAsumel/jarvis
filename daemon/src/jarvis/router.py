"""LLM routing — decides local (Ollama) vs cloud (Claude) per query."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from enum import Enum
from dataclasses import dataclass, field

import anthropic
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


# Keywords that force local (fast, private, no API cost)
_LOCAL_PATTERNS = frozenset({
    "disk", "memory", "cpu", "process", "pid", "journal", "log",
    "uptime", "service", "systemctl", "status", "df ", "free ",
    "ps ", "top", "kill", "network", "ip ", "port",
})

# Keywords that push to cloud (complex reasoning)
_CLOUD_PATTERNS = frozenset({
    "write code", "explain", "analyze", "debug", "implement",
    "architecture", "refactor", "design", "compare", "research",
    "what is", "how does", "why does", "best practice",
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

    def decide(self, query: str) -> Backend:
        if not self._cfg.anthropic_api_key:
            return Backend.LOCAL

        q = query.lower()

        # Explicit system/monitoring queries → always local (no latency, no cost)
        if any(p in q for p in _LOCAL_PATTERNS):
            return Backend.LOCAL

        # Long queries or complex reasoning keywords → cloud
        if len(query) > 300 or any(p in q for p in _CLOUD_PATTERNS):
            return Backend.CLOUD

        return Backend.LOCAL  # default: local (private + fast)

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
            async for chunk in self._claude_stream(messages, system):
                yield chunk
        else:
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
        local_ok = False
        cloud_ok  = bool(self._cfg.anthropic_api_key)
        try:
            await asyncio.wait_for(self._olla.list(), timeout=2.0)
            local_ok = True
        except Exception:
            pass
        return {"local": local_ok, "cloud": cloud_ok}
