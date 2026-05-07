"""Persistent memory: ChromaDB (semantic) + SQLite (structured)."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import chromadb
from chromadb.config import Settings

from .config import JarvisConfig

log = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    id: str
    content: str
    metadata: dict
    timestamp: str
    distance: float = 0.0


class JarvisMemory:
    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS interactions (
        id          TEXT PRIMARY KEY,
        role        TEXT NOT NULL,
        content     TEXT NOT NULL,
        metadata    TEXT DEFAULT '{}',
        created_at  TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS system_events (
        id          TEXT PRIMARY KEY,
        event_type  TEXT NOT NULL,
        details     TEXT NOT NULL,
        created_at  TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS preferences (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    """

    def __init__(self, config: JarvisConfig) -> None:
        self._cfg = config
        self._chroma: chromadb.ClientAPI | None = None
        self._coll: chromadb.Collection | None  = None
        self._db: sqlite3.Connection | None     = None

    def initialize(self) -> None:
        self._cfg.memory_dir.mkdir(parents=True, exist_ok=True)
        self._cfg.chroma_dir.mkdir(parents=True, exist_ok=True)

        self._chroma = chromadb.PersistentClient(
            path=str(self._cfg.chroma_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self._coll = self._chroma.get_or_create_collection(
            name="jarvis_memory",
            metadata={"hnsw:space": "cosine"},
        )

        self._db = sqlite3.connect(
            str(self._cfg.memory_dir / "jarvis.db"),
            check_same_thread=False,
        )
        self._db.row_factory = sqlite3.Row
        self._db.executescript(self._SCHEMA)
        self._db.commit()
        log.info("memory initialised — chroma=%s sqlite=%s", self._cfg.chroma_dir, self._cfg.memory_dir)

    # ── Write ──────────────────────────────────────────────────────────────────

    def store_interaction(self, role: str, content: str, metadata: dict | None = None) -> str:
        entry_id = str(uuid.uuid4())
        ts       = datetime.now().isoformat()
        meta     = {**(metadata or {}), "role": role, "timestamp": ts}

        # ChromaDB — semantic index
        self._coll.add(documents=[content], metadatas=[meta], ids=[entry_id])

        # SQLite — structured log
        self._db.execute(
            "INSERT INTO interactions VALUES (?, ?, ?, ?, ?)",
            (entry_id, role, content, json.dumps(meta), ts),
        )
        self._db.commit()
        return entry_id

    def store_system_event(self, event_type: str, details: str) -> None:
        self._db.execute(
            "INSERT INTO system_events VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), event_type, details, datetime.now().isoformat()),
        )
        self._db.commit()

    def set_preference(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO preferences VALUES (?, ?, ?)",
            (key, value, datetime.now().isoformat()),
        )
        self._db.commit()

    # ── Read ───────────────────────────────────────────────────────────────────

    def search(self, query: str, n: int = 5) -> list[MemoryEntry]:
        if self._coll.count() == 0:
            return []
        results = self._coll.query(query_texts=[query], n_results=min(n, self._coll.count()))
        entries: list[MemoryEntry] = []
        for doc, meta, eid, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["ids"][0],
            results["distances"][0],
        ):
            entries.append(MemoryEntry(
                id=eid, content=doc, metadata=meta,
                timestamp=meta.get("timestamp", ""), distance=dist,
            ))
        return entries

    def get_recent(self, limit: int = 20) -> list[MemoryEntry]:
        rows = self._db.execute(
            "SELECT * FROM interactions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            MemoryEntry(
                id=r["id"], content=r["content"],
                metadata=json.loads(r["metadata"]), timestamp=r["created_at"],
            )
            for r in rows
        ]

    def get_preference(self, key: str, default: str = "") -> str:
        row = self._db.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def build_context_string(self, query: str, max_chars: int = 2000) -> str:
        relevant = self.search(query, n=5)
        recent   = self.get_recent(limit=6)
        seen     = {e.id for e in relevant}
        combined = relevant + [e for e in recent if e.id not in seen]

        lines = []
        total = 0
        for entry in combined:
            role = entry.metadata.get("role", "?")
            line = f"[{role}] {entry.content}"
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)
        return "\n".join(lines)

    def close(self) -> None:
        if self._db:
            self._db.close()
