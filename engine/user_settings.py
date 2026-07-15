from __future__ import annotations

import time

from workflows.segments import DEFAULT_ARCHIVE_DAYS, DEFAULT_NEW_DAYS

KEYS = {
    "results.new_days": {
        "label": "A tender counts as new for",
        "unit": "days",
        "help": "How long a fresh find stays in your inbox before it moves to the shortlist.",
        "min": 1, "max": 90, "default": DEFAULT_NEW_DAYS,
    },
    "results.archive_after_days": {
        "label": "Archive a tender after",
        "unit": "days",
        "help": "Relevant tenders older than this drop into the archive, deadline aside.",
        "min": 7, "max": 365, "default": DEFAULT_ARCHIVE_DAYS,
    },
}


class Overlay:
    def __init__(self, store, overrides):
        self._store = store
        self._over = overrides or {}

    def get(self, key, default=None):
        if key in self._over:
            return self._over[key]
        return self._store.get(key, default)

    def __getattr__(self, name):
        return getattr(self._store, name)


def raw(conn, acct_id):
    if not acct_id:
        return {}
    rows = conn.execute("SELECT key, value FROM account_settings WHERE account_id=?",
                        (acct_id,)).fetchall()
    return {r["key"]: r["value"] for r in rows if r["key"] in KEYS}


def effective(conn, store, acct_id):
    out = {}
    for key, meta in KEYS.items():
        out[key] = int(store.get(key, meta["default"]))
    for key, value in raw(conn, acct_id).items():
        try:
            out[key] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def view(conn, store, acct_id):
    if not acct_id:
        return store
    over = raw(conn, acct_id)
    clean = {}
    for key, value in over.items():
        try:
            clean[key] = int(value)
        except (TypeError, ValueError):
            continue
    return Overlay(store, clean) if clean else store


def clamp(key, value):
    meta = KEYS[key]
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{meta['label']} must be a whole number")
    if not meta["min"] <= n <= meta["max"]:
        raise ValueError(f"{meta['label']} must be between {meta['min']} and {meta['max']}")
    return n


def set_many(conn, acct_id, values):
    if not acct_id:
        raise ValueError("token mode has no per-account settings")
    cleaned = {k: clamp(k, v) for k, v in values.items() if k in KEYS}
    for key, n in cleaned.items():
        conn.execute(
            "INSERT INTO account_settings(account_id,key,value,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(account_id,key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (acct_id, key, str(n), time.time()))
    conn.commit()
    return cleaned


def reset(conn, acct_id):
    conn.execute("DELETE FROM account_settings WHERE account_id=?", (acct_id,))
    conn.commit()
