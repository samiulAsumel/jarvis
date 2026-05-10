"""Standalone ChromaDB vector store for scripting / legacy use.

The full production memory layer (ChromaDB + SQLite + context building)
lives in daemon/src/jarvis/memory.py.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import chromadb
from chromadb.config import Settings


@dataclass
class VectorEntry:
    id:       str
    content:  str
    metadata: dict
    distance: float = 0.0


class VectorStore:
    def __init__(
        self,
        persist_dir: str | Path = Path.home() / ".local/share/jarvis/chroma",
        collection:  str        = "jarvis",
    ) -> None:
        self._dir = Path(persist_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self._dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self._coll = self._client.get_or_create_collection(
            name=collection,
            metadata={"hnsw:space": "cosine"},
        )

    # ── Write ──────────────────────────────────────────────────────────────────

    def add(self, content: str, metadata: dict | None = None) -> str:
        entry_id = str(uuid.uuid4())
        meta = {**(metadata or {}), "timestamp": datetime.now().isoformat()}
        self._coll.add(documents=[content], metadatas=[meta], ids=[entry_id])
        return entry_id

    def add_batch(self, items: list[tuple[str, dict]]) -> list[str]:
        ids  = [str(uuid.uuid4()) for _ in items]
        ts   = datetime.now().isoformat()
        docs = [text for text, _ in items]
        metas = [{**m, "timestamp": ts} for _, m in items]
        self._coll.add(documents=docs, metadatas=metas, ids=ids)
        return ids

    # ── Read ───────────────────────────────────────────────────────────────────

    def search(self, query: str, n: int = 5) -> list[VectorEntry]:
        count = self._coll.count()
        if count == 0:
            return []
        results = self._coll.query(
            query_texts=[query],
            n_results=min(n, count),
        )
        return [
            VectorEntry(id=eid, content=doc, metadata=meta, distance=dist)
            for doc, meta, eid, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["ids"][0],
                results["distances"][0],
            )
        ]

    def count(self) -> int:
        return self._coll.count()

    # ── Delete ─────────────────────────────────────────────────────────────────

    def delete(self, entry_id: str) -> None:
        self._coll.delete(ids=[entry_id])

    def clear(self) -> None:
        self._client.delete_collection(self._coll.name)
        self._coll = self._client.get_or_create_collection(
            name=self._coll.name,
            metadata={"hnsw:space": "cosine"},
        )
