from __future__ import annotations

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JarvisConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path.home() / ".config/jarvis/.env",
        env_prefix="JARVIS_",
        extra="ignore",
    )

    # ── Daemon ────────────────────────────────────────────────────────────────
    host: str      = "127.0.0.1"
    port: int      = 8787
    log_level: str = "INFO"
    config_dir: Path = Field(default_factory=lambda: Path.home() / ".config/jarvis")

    # ── Local LLM (Ollama) ────────────────────────────────────────────────────
    ollama_url: str        = "http://127.0.0.1:11434"
    ollama_model: str      = "llama3.3:70b"   # reasoning / complex ops
    ollama_fast_model: str = "qwen2.5:7b"     # quick system queries

    # ── Cloud LLM (Anthropic Claude) ──────────────────────────────────────────
    anthropic_api_key: str = ""
    claude_model: str      = "claude-sonnet-4-6"

    # ── Cloud LLM (OpenRouter — fast, many models) ────────────────────────────
    openrouter_api_key: str  = ""
    openrouter_model: str    = "nvidia/nemotron-3-super-120b-a12b:free"  # best free model
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # ── Free LLM (Groq — ultra-fast, free tier, Llama 3.3 70B) ───────────────
    groq_api_key: str   = ""
    groq_model: str     = "llama-3.3-70b-versatile"
    groq_base_url: str  = "https://api.groq.com/openai/v1"

    # ── Free LLM (Google Gemini — free tier, gemini-2.0-flash) ───────────────
    gemini_api_key: str = ""
    gemini_model: str   = "gemini-2.0-flash"

    # ── Memory ────────────────────────────────────────────────────────────────
    memory_dir: Path = Field(default_factory=lambda: Path.home() / ".local/share/jarvis/memory")
    chroma_dir: Path = Field(default_factory=lambda: Path.home() / ".local/share/jarvis/chroma")

    # ── Voice ─────────────────────────────────────────────────────────────────
    whisper_binary: Path  = Path("/run/current-system/sw/bin/whisper-cpp")
    whisper_model: str    = "base.en"         # tiny | base | small | medium | large
    piper_binary: Path    = Path("/run/current-system/sw/bin/piper")
    piper_voice: str      = "en_US-ryan-high"
    piper_model_dir: Path = Field(default_factory=lambda: Path.home() / ".local/share/piper")
    wake_word: str        = "jarvis"
    voice_threshold: float = 0.5
    sample_rate: int       = 16000

    # ── Security ──────────────────────────────────────────────────────────────
    allowed_service_prefixes: list[str] = Field(
        default=["jarvis", "ollama", "pipewire", "NetworkManager", "bluetooth"]
    )
    safe_read_roots: list[Path] = Field(
        default_factory=lambda: [Path.home(), Path("/etc/nixos"), Path("/var/log"), Path("/proc")]
    )
    safe_write_roots: list[Path] = Field(
        default_factory=lambda: [Path.home() / ".config/jarvis", Path("/etc/nixos")]
    )
    nixos_config_dir: Path = Path("/etc/nixos")

    def load_api_key(self) -> str:
        key_file = self.config_dir / "anthropic_key"
        if not self.anthropic_api_key and key_file.exists():
            self.anthropic_api_key = key_file.read_text().strip()
        return self.anthropic_api_key

    def is_safe_read(self, path: Path) -> bool:
        resolved = path.resolve()
        return any(resolved.is_relative_to(r) for r in self.safe_read_roots)

    def is_safe_write(self, path: Path) -> bool:
        resolved = path.resolve()
        return any(resolved.is_relative_to(r) for r in self.safe_write_roots)


_config: JarvisConfig | None = None


def get_config() -> JarvisConfig:
    global _config
    if _config is None:
        _config = JarvisConfig()
        _config.load_api_key()
    return _config
