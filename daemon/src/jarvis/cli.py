"""JARVIS CLI — `jarvis` command. Entry point: jarvis.cli:app

Commands wired in home.nix:
  j   → jarvis chat          (interactive)
  jv  → jarvis voice         (wake-word listener)
  js  → jarvis status        (health + system context)
  Super+J → jarvis overlay   (floating wezterm chat window)
"""

from __future__ import annotations

import subprocess
import sys

import httpx
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

app     = typer.Typer(name="jarvis", help="JARVIS — Personal AI OS", add_completion=False, no_args_is_help=False)
console = Console()

_DAEMON_DOWN = "[red]Daemon offline — run: systemctl start jarvis-daemon[/red]"


# ── helpers ───────────────────────────────────────────────────────────────────

def _base_url() -> str:
    from .config import get_config
    cfg = get_config()
    return f"http://{cfg.host}:{cfg.port}"


def _client() -> httpx.Client:
    # connect=10s, first-byte read=60s, total read=600s (14B model can take 5+ min on CPU)
    return httpx.Client(
        base_url=_base_url(),
        timeout=httpx.Timeout(connect=10, read=600, write=60, pool=10),
    )


# ── chat ──────────────────────────────────────────────────────────────────────

@app.command()
def chat(
    query: str = typer.Argument(None, help="One-shot query (omit for interactive mode)"),
):
    """Interactive or one-shot chat with JARVIS."""
    if query:
        _send_chat(query)
        return

    console.print(Panel(
        "[bold cyan]JARVIS[/bold cyan] — Just A Rather Very Intelligent System\n"
        "[dim]Type [bold]exit[/bold] to quit · [bold]clear[/bold] to reset context[/dim]",
        border_style="cyan",
        expand=False,
    ))
    history: list[dict] = []
    while True:
        try:
            raw = console.input("[bold green]You >[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye, sir.[/dim]")
            break
        if not raw:
            continue
        if raw.lower() in {"exit", "quit", "bye", "shutdown"}:
            console.print("[dim]Goodbye, sir.[/dim]")
            break
        if raw.lower() == "clear":
            history.clear()
            console.print("[dim]Context cleared.[/dim]")
            continue
        _send_chat(raw, history=history)


def _send_chat(query: str, history: list[dict] | None = None) -> None:
    h = history if history is not None else []
    try:
        with _client() as c:
            with console.status("[cyan]JARVIS is thinking… (14B model may take 1-3 min on CPU)[/cyan]", spinner="dots"):
                resp = c.post("/api/chat", json={"query": query, "history": h})
            resp.raise_for_status()
            reply = resp.json()["reply"]
        console.print(Panel(Markdown(reply), title="[bold cyan]JARVIS[/bold cyan]", border_style="cyan"))
        h.append({"role": "user",      "content": query})
        h.append({"role": "assistant", "content": reply})
    except httpx.ConnectError:
        console.print(_DAEMON_DOWN)
    except httpx.ReadTimeout:
        console.print("[yellow]JARVIS took too long to respond. Try a shorter query or restart the daemon.[/yellow]")
    except httpx.HTTPStatusError as e:
        console.print(f"[red]HTTP {e.response.status_code}[/red]: {e.response.text[:200]}")


# ── status / health ───────────────────────────────────────────────────────────

@app.command()
def status():
    """Daemon health + live system context (alias: js)."""
    try:
        with _client() as c:
            h   = c.get("/health").json()
            ctx = c.get("/api/system/context").json()["context"]

        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("Component", style="dim", width=14)
        table.add_column("Status")
        table.add_row("daemon",    "[green]online[/green]")
        table.add_row("local LLM", "[green]ready[/green]"   if h["llm"]["local"] else "[red]offline[/red]")
        table.add_row("cloud LLM", "[green]ready[/green]"   if h["llm"]["cloud"] else "[yellow]no key[/yellow]")
        console.print(table)
        console.print(Panel(ctx, title="[bold]System[/bold]", border_style="blue"))
    except httpx.ConnectError:
        console.print(_DAEMON_DOWN)


@app.command()
def health():
    """Check daemon and LLM backend health."""
    status()


# ── speak ──────────────────────────────────────────────────────────────────────

@app.command()
def speak(text: str = typer.Argument(..., help="Text to synthesize and play")):
    """Speak text via Piper TTS (non-blocking)."""
    try:
        with _client() as c:
            c.post("/api/voice/speak", json={"text": text}).raise_for_status()
        console.print(f"[cyan]Speaking:[/cyan] {text}")
    except httpx.ConnectError:
        console.print(_DAEMON_DOWN)


# ── voice ──────────────────────────────────────────────────────────────────────

@app.command()
def voice():
    """Start the wake-word voice listener (alias: jv)."""
    console.print("[cyan]Starting JARVIS voice listener…[/cyan]")
    from .voice.wake import main as _wake
    _wake()


# ── overlay ───────────────────────────────────────────────────────────────────

@app.command()
def overlay():
    """Open a floating JARVIS chat window (triggered by Super+J in Hyprland)."""
    subprocess.Popen(
        ["wezterm", "start", "--class", "jarvis-overlay", "--", "jarvis", "chat"],
        start_new_session=True,
    )


# ── system ────────────────────────────────────────────────────────────────────

@app.command()
def system():
    """Show live system diagnostics."""
    try:
        with _client() as c:
            ctx = c.get("/api/system/context").json()["context"]
        console.print(Panel(ctx, title="[bold]System[/bold]", border_style="blue"))
    except httpx.ConnectError:
        console.print(_DAEMON_DOWN)


# ── agent ──────────────────────────────────────────────────────────────────────

@app.command()
def agent(
    op:     str       = typer.Argument(..., help="Op: disk_usage | memory_info | cpu_info | process_list | network_info | journal_tail | …"),
    params: list[str] = typer.Argument(None, help="key=value pairs (e.g. unit=ollama lines=100)"),
):
    """Run a whitelisted system agent operation directly."""
    kw: dict = {}
    for pair in (params or []):
        k, _, v = pair.partition("=")
        kw[k.strip()] = v.strip()
    try:
        with _client() as c:
            result = c.post("/api/agent", json={"op": op, "kwargs": kw}).json()
        if result["success"]:
            console.print(result["output"])
        else:
            console.print(f"[red]Error:[/red] {result['error']}")
    except httpx.ConnectError:
        console.print(_DAEMON_DOWN)


# ── memory ────────────────────────────────────────────────────────────────────

memory_app = typer.Typer(name="memory", help="JARVIS memory commands", add_completion=False)
app.add_typer(memory_app)


@memory_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Semantic search query"),
    n:     int = typer.Option(5, help="Number of results"),
):
    """Semantic search over JARVIS memory."""
    try:
        with _client() as c:
            entries = c.get("/api/memory/search", params={"q": query, "n": n}).json()["entries"]
        for e in entries:
            console.print(Panel(
                e["content"],
                subtitle=f"[dim]{e['timestamp']}  dist={e['distance']:.3f}[/dim]",
                border_style="dim",
            ))
    except httpx.ConnectError:
        console.print(_DAEMON_DOWN)


@memory_app.command("recent")
def memory_recent(limit: int = typer.Argument(10, help="Number of entries to show")):
    """Show recent JARVIS memory entries."""
    try:
        with _client() as c:
            entries = c.get("/api/memory/recent", params={"limit": limit}).json()["entries"]
        for e in entries:
            role   = e["metadata"].get("role", "?")
            colour = "cyan" if role == "assistant" else "green"
            console.print(
                f"[dim]{e['timestamp']}[/dim] [{colour}]{role}[/{colour}]  {e['content'][:140]}"
            )
    except httpx.ConnectError:
        console.print(_DAEMON_DOWN)


# ── entry ──────────────────────────────────────────────────────────────────────

def main() -> None:
    """Bare `jarvis` with no args opens interactive chat."""
    if len(sys.argv) == 1:
        sys.argv.append("chat")
    app()


if __name__ == "__main__":
    main()
