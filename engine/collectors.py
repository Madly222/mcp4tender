from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .hashing import content_hash

log = logging.getLogger("tenderengine.collector")

_COLLECTORS: dict[str, type] = {}


def register_collector(name: str):
    def deco(cls):
        cls.source = name
        _COLLECTORS[name] = cls
        return cls
    return deco


def get_collector(name: str):
    if name not in _COLLECTORS:
        raise KeyError(f"collector not registered: {name}")
    return _COLLECTORS[name]()


def all_collectors() -> list[str]:
    return sorted(_COLLECTORS)


@dataclass
class CollectContext:
    config: Any
    cursor: str | None
    source_config: dict
    params: dict = field(default_factory=dict)


@dataclass
class CollectedItem:
    external_id: str
    raw: dict
    normalized: dict


@dataclass
class CollectResult:
    items: list = field(default_factory=list)
    cursor: str | None = None
    fetched: int = 0
    too_old: int = 0


class Collector(ABC):
    source: str = ""

    @abstractmethod
    def collect(self, ctx: CollectContext) -> CollectResult: ...

    def normalize(self, raw, external_id):
        raise NotImplementedError


def _read_cursor(conn, source):
    row = conn.execute("SELECT cursor FROM source_state WHERE source = ?", (source,)).fetchone()
    return row["cursor"] if row else None


def _write_cursor(conn, source, cursor, count):
    now = time.time()
    conn.execute(
        "INSERT INTO source_state(source, cursor, last_count, last_run_at) VALUES(?,?,?,?) "
        "ON CONFLICT(source) DO UPDATE SET cursor=excluded.cursor, "
        "last_count=excluded.last_count, last_run_at=excluded.last_run_at",
        (source, cursor, count, now),
    )
    conn.commit()


def _origin_for(params):
    return "backfill" if (params or {}).get("mode") == "backfill" else "incremental"


def _store_item(conn, source, item: CollectedItem, origin="incremental"):
    now = time.time()
    if conn.execute("SELECT 1 FROM dismissed_tenders WHERE external_id = ?",
                    (item.external_id,)).fetchone():
        return False
    chash = content_hash(item.normalized)
    conn.execute(
        "INSERT OR IGNORE INTO raw_documents(source, external_id, content_hash, fetched_at, "
        "payload_json) VALUES(?,?,?,?,?)",
        (source, item.external_id, chash, now, json.dumps(item.raw, ensure_ascii=False)),
    )
    existing = conn.execute(
        "SELECT id, content_hash FROM tenders WHERE source = ? AND external_id = ?",
        (source, item.external_id),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO tenders(source, external_id, content_hash, normalized_json, status, "
            "origin, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (source, item.external_id, chash,
             json.dumps(item.normalized, ensure_ascii=False), "new", origin, now, now),
        )
        return True
    if existing["content_hash"] != chash:
        conn.execute(
            "UPDATE tenders SET content_hash = ?, normalized_json = ?, status = ?, updated_at = ? "
            "WHERE id = ?",
            (chash, json.dumps(item.normalized, ensure_ascii=False), "updated", now,
             existing["id"]),
        )
        return True
    return False


def renormalize_source(source, store, conn):
    collector = get_collector(source)
    if not hasattr(collector, "normalize"):
        return {"source": source, "status": "unsupported"}
    rows = conn.execute(
        "SELECT external_id, payload_json FROM raw_documents WHERE source = ? ORDER BY id DESC",
        (source,),
    ).fetchall()
    updated = 0
    seen = set()
    for row in rows:
        ext = row["external_id"]
        if ext in seen:
            continue
        seen.add(ext)
        try:
            raw = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            continue
        normalized = collector.normalize(raw, ext)
        chash = content_hash(normalized)
        conn.execute(
            "UPDATE tenders SET normalized_json = ?, content_hash = ?, updated_at = ? "
            "WHERE source = ? AND external_id = ?",
            (json.dumps(normalized, ensure_ascii=False), chash, time.time(), source, ext),
        )
        updated += 1
    conn.commit()
    return {"source": source, "status": "done", "updated": updated}


def run_collector(source, store, conn, params=None):
    source_config = store.get(f"sources.{source}", {})
    if not source_config.get("enabled", False):
        return {"source": source, "status": "disabled", "fetched": 0, "new": 0}

    collector = get_collector(source)
    cursor_before = _read_cursor(conn, source)
    started = time.time()
    conn.execute(
        "INSERT INTO source_runs(source, started_at, cursor_before, status) VALUES(?,?,?,?)",
        (source, started, cursor_before, "running"),
    )
    conn.commit()
    run_row_id = conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]

    try:
        ctx = CollectContext(config=store, cursor=cursor_before, source_config=source_config,
                             params=params or {})
        result = collector.collect(ctx)
        origin = _origin_for(params)
        new_count = 0
        for item in result.items:
            if _store_item(conn, source, item, origin):
                new_count += 1
        conn.commit()
        cursor_after = result.cursor if result.cursor is not None else cursor_before
        _write_cursor(conn, source, cursor_after, result.fetched)
        conn.execute(
            "UPDATE source_runs SET finished_at = ?, fetched = ?, new_items = ?, "
            "cursor_after = ?, status = ? WHERE id = ?",
            (time.time(), result.fetched, new_count, cursor_after, "done", run_row_id),
        )
        conn.commit()
        log.info("source=%s done: fetched=%d new=%d (deduped=%d)",
                 source, result.fetched, new_count, result.fetched - new_count)
        return {"source": source, "status": "done", "fetched": result.fetched,
                "new": new_count, "too_old": result.too_old, "cursor": cursor_after}
    except Exception as exc:
        log.exception("source=%s collect failed", source)
        conn.execute(
            "UPDATE source_runs SET finished_at = ?, status = ?, error = ? WHERE id = ?",
            (time.time(), "error", str(exc), run_row_id),
        )
        conn.commit()
        return {"source": source, "status": "error", "error": str(exc)}
