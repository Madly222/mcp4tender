from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class ConfigStore:
    def __init__(self, conn):
        self.conn = conn
        self._cache: dict[str, Any] = {}
        self._generation = -1

    def _db_generation(self) -> int:
        row = self.conn.execute(
            "SELECT value FROM config_meta WHERE key='generation'"
        ).fetchone()
        return int(row[0]) if row else 0

    def _bump_generation(self) -> None:
        self.conn.execute(
            "UPDATE config_meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
            "WHERE key='generation'"
        )

    def reload(self) -> None:
        rows = self.conn.execute(
            "SELECT key, value_json FROM configs WHERE active = 1"
        ).fetchall()
        self._cache = {r["key"]: json.loads(r["value_json"]) for r in rows}
        self._generation = self._db_generation()

    def _ensure_fresh(self) -> None:
        if self._db_generation() != self._generation:
            self.reload()

    def get(self, key: str, default: Any = None) -> Any:
        self._ensure_fresh()
        return self._cache.get(key, default)

    def all(self) -> dict[str, Any]:
        self._ensure_fresh()
        return dict(self._cache)

    def set(self, key: str, value: Any, actor: str = "system", note: str = "") -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM configs WHERE key = ?", (key,)
        ).fetchone()
        version = int(row["v"]) + 1
        now = time.time()
        self.conn.execute("UPDATE configs SET active = 0 WHERE key = ?", (key,))
        self.conn.execute(
            "INSERT INTO configs(key, version, value_json, active, note, actor, created_at) "
            "VALUES(?,?,?,1,?,?,?)",
            (key, version, json.dumps(value, ensure_ascii=False), note, actor, now),
        )
        self.conn.execute(
            "INSERT INTO audit_log(ts, actor, action, entity, detail_json) VALUES(?,?,?,?,?)",
            (now, actor, "config.set", key, json.dumps({"version": version, "note": note})),
        )
        self._bump_generation()
        self.conn.commit()
        self.reload()
        return version

    def history(self, key: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT version, active, note, actor, created_at FROM configs "
            "WHERE key = ? ORDER BY version DESC",
            (key,),
        ).fetchall()
        return [dict(r) for r in rows]

    def rollback(self, key: str, version: int, actor: str = "system") -> int:
        row = self.conn.execute(
            "SELECT value_json FROM configs WHERE key = ? AND version = ?",
            (key, version),
        ).fetchone()
        if row is None:
            raise KeyError(f"config {key} v{version} not found")
        return self.set(key, json.loads(row["value_json"]), actor=actor,
                        note=f"rollback to v{version}")

    def seed_defaults(self, defaults_dir: str | Path, actor: str = "seed") -> list[str]:
        seeded = []
        for path in sorted(Path(defaults_dir).glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, value in data.items():
                exists = self.conn.execute(
                    "SELECT 1 FROM configs WHERE key = ? LIMIT 1", (key,)
                ).fetchone()
                if exists is None:
                    self.set(key, value, actor=actor, note=f"seed from {path.name}")
                    seeded.append(key)
        return seeded
