"""System agent — safe, whitelisted operations only. No arbitrary shell execution."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

import psutil

from .config import JarvisConfig

log = logging.getLogger(__name__)


class Op(str, Enum):
    DISK_USAGE       = "disk_usage"
    MEMORY_INFO      = "memory_info"
    CPU_INFO         = "cpu_info"
    PROCESS_LIST     = "process_list"
    JOURNAL_TAIL     = "journal_tail"
    NETWORK_INFO     = "network_info"
    RESTART_SERVICE  = "restart_service"
    STOP_SERVICE     = "stop_service"
    START_SERVICE    = "start_service"
    NIX_REBUILD_TEST = "nix_rebuild_test"
    NIX_REBUILD_SWITCH = "nix_rebuild_switch"
    NIX_FLAKE_UPDATE = "nix_flake_update"
    READ_FILE        = "read_file"
    WRITE_NIXOS_FILE = "write_nixos_file"


@dataclass
class AgentResult:
    op: Op
    success: bool
    output: str
    error: str | None = None
    timestamp: str    = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class SystemContext:
    cpu_percent: float
    memory_total_gb: float
    memory_used_gb: float
    memory_percent: float
    disk_total_gb: float
    disk_used_gb: float
    disk_percent: float
    load_avg: tuple[float, float, float]
    uptime_hours: float
    top_processes: list[dict]
    hostname: str


class SystemAgent:
    def __init__(self, config: JarvisConfig) -> None:
        self._cfg = config

    # ── Dispatch ───────────────────────────────────────────────────────────────

    async def execute(self, op: Op, **kwargs) -> AgentResult:
        handlers = {
            Op.DISK_USAGE:         self._disk_usage,
            Op.MEMORY_INFO:        self._memory_info,
            Op.CPU_INFO:           self._cpu_info,
            Op.PROCESS_LIST:       self._process_list,
            Op.JOURNAL_TAIL:       self._journal_tail,
            Op.NETWORK_INFO:       self._network_info,
            Op.RESTART_SERVICE:    self._restart_service,
            Op.STOP_SERVICE:       self._stop_service,
            Op.START_SERVICE:      self._start_service,
            Op.NIX_REBUILD_TEST:   self._nix_rebuild_test,
            Op.NIX_REBUILD_SWITCH: self._nix_rebuild_switch,
            Op.NIX_FLAKE_UPDATE:   self._nix_flake_update,
            Op.READ_FILE:          self._read_file,
            Op.WRITE_NIXOS_FILE:   self._write_nixos_file,
        }
        handler = handlers.get(op)
        if handler is None:
            return AgentResult(op=op, success=False, output="", error=f"Unknown op: {op}")
        try:
            return await handler(**kwargs)
        except Exception as e:
            log.exception("agent op %s failed", op)
            return AgentResult(op=op, success=False, output="", error=str(e))

    # ── System info (pure Python — no subprocess) ─────────────────────────────

    async def _disk_usage(self) -> AgentResult:
        lines = []
        for part in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(part.mountpoint)
                lines.append(
                    f"{part.mountpoint}: {u.used/1e9:.1f}G / {u.total/1e9:.1f}G "
                    f"({u.percent:.0f}% used)"
                )
            except PermissionError:
                pass
        return AgentResult(op=Op.DISK_USAGE, success=True, output="\n".join(lines))

    async def _memory_info(self) -> AgentResult:
        vm  = psutil.virtual_memory()
        sw  = psutil.swap_memory()
        out = (
            f"RAM:  {vm.used/1e9:.1f}G / {vm.total/1e9:.1f}G ({vm.percent:.0f}% used)\n"
            f"Swap: {sw.used/1e9:.1f}G / {sw.total/1e9:.1f}G ({sw.percent:.0f}% used)"
        )
        return AgentResult(op=Op.MEMORY_INFO, success=True, output=out)

    async def _cpu_info(self) -> AgentResult:
        per_core = psutil.cpu_percent(interval=1, percpu=True)
        avg      = sum(per_core) / len(per_core)
        la       = psutil.getloadavg()
        freq     = psutil.cpu_freq()
        out = (
            f"Average: {avg:.1f}%  Cores: {len(per_core)}\n"
            f"Load avg (1/5/15): {la[0]:.2f} {la[1]:.2f} {la[2]:.2f}\n"
            f"Freq: {freq.current:.0f} MHz (max {freq.max:.0f} MHz)"
        )
        return AgentResult(op=Op.CPU_INFO, success=True, output=out)

    async def _process_list(self, n: int = 15) -> AgentResult:
        procs = sorted(
            (p.info for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"])
             if p.info["cpu_percent"] is not None),
            key=lambda x: x["cpu_percent"],
            reverse=True,
        )[:n]
        lines = [f"{'PID':>6}  {'CPU%':>5}  {'MEM%':>5}  NAME"]
        for p in procs:
            lines.append(f"{p['pid']:>6}  {p['cpu_percent']:>5.1f}  {p['memory_percent']:>5.1f}  {p['name']}")
        return AgentResult(op=Op.PROCESS_LIST, success=True, output="\n".join(lines))

    async def _network_info(self) -> AgentResult:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        io    = psutil.net_io_counters(pernic=True)
        lines = []
        for iface, addr_list in addrs.items():
            st  = stats.get(iface)
            nio = io.get(iface)
            ips = [a.address for a in addr_list if a.family.name in ("AF_INET", "AF_INET6")]
            up  = "UP" if st and st.isup else "DOWN"
            rx  = f"{nio.bytes_recv/1e6:.1f}MB rx" if nio else ""
            tx  = f"{nio.bytes_sent/1e6:.1f}MB tx" if nio else ""
            lines.append(f"{iface} [{up}]  {' '.join(ips)}  {rx} {tx}".strip())
        return AgentResult(op=Op.NETWORK_INFO, success=True, output="\n".join(lines))

    # ── Journal ────────────────────────────────────────────────────────────────

    async def _journal_tail(self, unit: str = "", lines: int = 50) -> AgentResult:
        cmd = ["journalctl", "--no-pager", f"-n{lines}", "--output=short-monotonic"]
        if unit:
            cmd += ["-u", unit]
        return await self._run_safe(Op.JOURNAL_TAIL, cmd)

    # ── Service management ─────────────────────────────────────────────────────

    def _assert_service_allowed(self, service: str) -> None:
        if not any(service.startswith(p) for p in self._cfg.allowed_service_prefixes):
            raise PermissionError(
                f"Service '{service}' not in allowed prefixes: {self._cfg.allowed_service_prefixes}"
            )

    async def _restart_service(self, service: str) -> AgentResult:
        self._assert_service_allowed(service)
        return await self._run_safe(Op.RESTART_SERVICE, ["systemctl", "restart", service])

    async def _stop_service(self, service: str) -> AgentResult:
        self._assert_service_allowed(service)
        return await self._run_safe(Op.STOP_SERVICE, ["systemctl", "stop", service])

    async def _start_service(self, service: str) -> AgentResult:
        self._assert_service_allowed(service)
        return await self._run_safe(Op.START_SERVICE, ["systemctl", "start", service])

    # ── NixOS self-update ──────────────────────────────────────────────────────

    async def _nix_rebuild_test(self) -> AgentResult:
        return await self._run_safe(
            Op.NIX_REBUILD_TEST,
            ["nixos-rebuild", "test", "--flake", f"{self._cfg.nixos_config_dir}#jarvis"],
            timeout=300,
        )

    async def _nix_rebuild_switch(self) -> AgentResult:
        return await self._run_safe(
            Op.NIX_REBUILD_SWITCH,
            ["nixos-rebuild", "switch", "--flake", f"{self._cfg.nixos_config_dir}#jarvis"],
            timeout=600,
        )

    async def _nix_flake_update(self) -> AgentResult:
        return await self._run_safe(
            Op.NIX_FLAKE_UPDATE,
            ["nix", "flake", "update", "--flake", str(self._cfg.nixos_config_dir)],
            timeout=120,
        )

    # ── File operations ────────────────────────────────────────────────────────

    async def _read_file(self, path: str) -> AgentResult:
        p = Path(path)
        if not self._cfg.is_safe_read(p):
            raise PermissionError(f"Read blocked: {path}")
        if not p.exists():
            return AgentResult(op=Op.READ_FILE, success=False, output="", error=f"File not found: {path}")
        content = p.read_text(errors="replace")
        return AgentResult(op=Op.READ_FILE, success=True, output=content[:8000])

    async def _write_nixos_file(self, path: str, content: str) -> AgentResult:
        p = Path(path)
        if not self._cfg.is_safe_write(p):
            raise PermissionError(f"Write blocked: {path}")
        backup = p.with_suffix(p.suffix + ".bak")
        if p.exists():
            shutil.copy2(p, backup)
        p.write_text(content)
        log.info("wrote nixos file %s (backup: %s)", p, backup)
        return AgentResult(op=Op.WRITE_NIXOS_FILE, success=True, output=f"Written: {path}")

    # ── System context snapshot ────────────────────────────────────────────────

    async def get_system_context(self) -> SystemContext:
        vm   = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        la   = psutil.getloadavg()
        boot = psutil.boot_time()
        uptime_h = (datetime.now().timestamp() - boot) / 3600
        top = sorted(
            (p.info for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"])
             if p.info["cpu_percent"] is not None),
            key=lambda x: x["cpu_percent"], reverse=True,
        )[:5]
        import socket
        return SystemContext(
            cpu_percent    = psutil.cpu_percent(interval=0.5),
            memory_total_gb= vm.total / 1e9,
            memory_used_gb = vm.used  / 1e9,
            memory_percent = vm.percent,
            disk_total_gb  = disk.total / 1e9,
            disk_used_gb   = disk.used  / 1e9,
            disk_percent   = disk.percent,
            load_avg       = la,
            uptime_hours   = uptime_h,
            top_processes  = top,
            hostname       = socket.gethostname(),
        )

    async def get_context_string(self) -> str:
        ctx = await self.get_system_context()
        return (
            f"Host: {ctx.hostname} | Uptime: {ctx.uptime_hours:.1f}h\n"
            f"CPU: {ctx.cpu_percent:.1f}%  Load: {ctx.load_avg[0]:.2f}\n"
            f"RAM: {ctx.memory_used_gb:.1f}/{ctx.memory_total_gb:.1f}G ({ctx.memory_percent:.0f}%)\n"
            f"Disk: {ctx.disk_used_gb:.1f}/{ctx.disk_total_gb:.1f}G ({ctx.disk_percent:.0f}%)"
        )

    # ── Helper ─────────────────────────────────────────────────────────────────

    async def _run_safe(self, op: Op, cmd: list[str], timeout: float = 30) -> AgentResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            ok  = proc.returncode == 0
            out = (stdout + stderr).decode(errors="replace")
            return AgentResult(op=op, success=ok, output=out,
                               error=None if ok else f"exit {proc.returncode}")
        except asyncio.TimeoutError:
            return AgentResult(op=op, success=False, output="", error=f"timeout after {timeout}s")
