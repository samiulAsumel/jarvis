<div align="center">

# 🤖 JARVIS

**Just A Rather Very Intelligent System**

*Your personal AI — for everything. Code, science, writing, system ops, any language.*

[![NixOS](https://img.shields.io/badge/NixOS-5277C3?style=flat&logo=nixos&logoColor=white)](https://nixos.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[Features](#features) · [Quick Start](#quick-start) · [AI Backends](#ai-backends) · [Web UI](#web-ui)

</div>

---

## What is JARVIS?

JARVIS is a **self-hosted personal AI assistant** with a sleek web interface. Think Tony Stark's JARVIS — efficient, confident, occasionally dry — but running on your own machine, free, with no data leaving unless you choose it.

Ask anything. Upload files, code, or entire folders. Talk to it in Bengali, Banglish, or English. It remembers everything across sessions.

---

## Features

### 🧠 Intelligence
- **Smart model routing** — automatically picks the best model per query type (science → Qwen3 32B chain-of-thought, code → Llama 3.3 70B, creative → high temperature, math → low temperature)
- **Multi-backend LLM** — Groq (free, 376ms), OpenRouter (27 free models), Anthropic Claude, Google Gemini, local Ollama
- **Persistent memory** — remembers last 100 conversation exchanges across page reloads and browser restarts
- **Auto language detection** — Bengali script? Responds in Bengali. Banglish? Responds in Banglish. No need to say anything.

### 📎 File & Folder Upload
- **Images** — vision analysis via Llama 4 Scout (auto-switched when image attached)
- **Code & text files** — inject directly into context
- **Entire folders** — reads up to 80 files, builds structured context with file paths
- **Drag & drop** — drop files or folders anywhere on the page
- **Ctrl+V paste** — paste images straight from clipboard

### 🎙️ Voice
- **Voice input** — Web Speech API mic button on home and follow-up bar
- **Voice output** — Piper neural TTS (when daemon running) or browser speech synthesis

### 🖥️ Web UI
- Glass morphism dark design (cyan + purple, animated background)
- Streaming responses with markdown + syntax highlighting
- Recent chats on home page (click to re-run)
- Follow-up suggestions after each answer
- Conversation history in sidebar
- Model status chip with live backend indicator

### ⚙️ NixOS Integration (optional)
- Full NixOS flake configuration
- System monitoring (CPU, RAM, disk, processes, network)
- Service management via safe whitelist
- NixOS config management via daemon

---

## Quick Start

### Option A — Web UI only (no daemon needed)

```bash
git clone https://github.com/samiulAsumel/jarvis.git
cd jarvis
# Open web/index.html in your browser
# OR serve with any static server:
python -m http.server 8080 --directory web
```

Then open `http://localhost:8080` → click ⚙ → enter a free API key.

### Option B — Full daemon (NixOS)

```bash
git clone https://github.com/samiulAsumel/jarvis.git
cd jarvis

# Install Python dependencies
cd daemon
pip install -e ".[dev]"

# Add your API keys (chmod 600 for security)
mkdir -p ~/.config/jarvis
cat > ~/.config/jarvis/.env << EOF
JARVIS_GROQ_API_KEY=gsk_...
JARVIS_OPENROUTER_API_KEY=sk-or-v1-...
EOF
chmod 600 ~/.config/jarvis/.env

# Run the daemon
python -m jarvis.main
# → Open http://127.0.0.1:8787
```

---

## AI Backends

Priority order (auto-selected, no config needed):

| Backend | Model | Speed | Cost | Requires |
|---------|-------|-------|------|----------|
| **Groq** ⚡ | Llama 3.3 70B · Qwen3 32B · Llama 4 Scout | 376ms TTFT | Free | `GROQ_API_KEY` |
| **OpenRouter** | 27 free models (Nemotron, GPT-OSS, Gemma 4…) | ~1-3s | Free | `OPENROUTER_API_KEY` |
| **Anthropic** | Claude Sonnet 4.6 | ~1s | Paid | `ANTHROPIC_API_KEY` |
| **Gemini** | Gemini 2.0 Flash | ~1s | Free tier | `GEMINI_API_KEY` |
| **Ollama** | Llama 3.3 70B (local) | Hardware | Free | Local GPU |

**Get free API keys:**
- Groq: [console.groq.com/keys](https://console.groq.com/keys) — no credit card
- OpenRouter: [openrouter.ai/keys](https://openrouter.ai/keys) — no credit card

---

## Web UI

The entire UI is a single `web/index.html` file — no build step, no Node.js, no bundler.

**Works without the daemon** — connects directly to Groq or OpenRouter from the browser.

```
web/
└── index.html   ← complete SPA: UI + all JS + streaming + memory
```

**Key shortcuts:**
- `Enter` — send
- `Ctrl+V` — paste image from clipboard
- Drag & drop — files or folders anywhere
- Click 🧠 in navbar — clear memory
- Click ⚙ in navbar — API settings

---

## Project Structure

```
jarvis/
├── web/
│   └── index.html          # Full web UI (SPA, no build needed)
├── daemon/
│   └── src/jarvis/
│       ├── main.py          # FastAPI daemon entry point
│       ├── router.py        # LLM routing (Groq/OR/Claude/Gemini/Ollama)
│       ├── agent.py         # System operations (NixOS, services, files)
│       ├── memory.py        # ChromaDB + SQLite memory
│       ├── config.py        # Pydantic settings
│       └── voice/           # Whisper STT + Piper TTS
├── config/
│   └── settings.yaml        # Reference configuration
├── flake.nix                # NixOS flake
├── configuration.nix        # NixOS system config
└── home.nix                 # Home-manager config
```

---

## Configuration

All settings via environment variables (prefix `JARVIS_`) or `~/.config/jarvis/.env`:

```env
JARVIS_GROQ_API_KEY=gsk_...
JARVIS_GROQ_MODEL=llama-3.3-70b-versatile
JARVIS_OPENROUTER_API_KEY=sk-or-v1-...
JARVIS_ANTHROPIC_API_KEY=sk-ant-...
JARVIS_GEMINI_API_KEY=AIza...
JARVIS_HOST=127.0.0.1
JARVIS_PORT=8787
JARVIS_LOG_LEVEL=INFO
```

See [`config/settings.yaml`](config/settings.yaml) for all options with descriptions.

---

## License

MIT — do whatever you want with it.

---

<div align="center">
<sub>Built with FastAPI · Groq · OpenRouter · Ollama · NixOS · marked.js · highlight.js</sub>
</div>
