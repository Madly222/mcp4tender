from __future__ import annotations

import time

THEMES = (("dark", "Dark"), ("light", "Light"))

KEYS = {
    "ui.theme": {
        "label": "Theme",
        "help": "Dark is the default. Light is easier under office lighting or on a projector.",
        "choices": THEMES,
        "default": "dark",
    },
}

DEFAULTS = {k: m["default"] for k, m in KEYS.items()}


def raw(conn, acct_id):
    if not acct_id:
        return {}
    rows = conn.execute("SELECT key, value FROM account_settings WHERE account_id=?",
                        (acct_id,)).fetchall()
    return {r["key"]: r["value"] for r in rows if r["key"] in KEYS}


def effective(conn, acct_id):
    out = dict(DEFAULTS)
    for key, value in raw(conn, acct_id).items():
        if value in [c for c, _l in KEYS[key]["choices"]]:
            out[key] = value
    return out


def theme_of(request):
    acct = getattr(request.state, "account", None)
    if acct is None:
        return "dark"
    try:
        return effective(request.state.conn, acct["id"])["ui.theme"]
    except Exception:
        return "dark"


def clean(key, value):
    meta = KEYS.get(key)
    if not meta:
        raise ValueError(f"unknown setting {key}")
    allowed = [c for c, _l in meta["choices"]]
    if value not in allowed:
        raise ValueError(f"{meta['label']} must be one of: {', '.join(allowed)}")
    return value


def set_many(conn, acct_id, values):
    if not acct_id:
        raise ValueError("token mode has no per-account settings")
    cleaned = {k: clean(k, v) for k, v in values.items() if k in KEYS}
    for key, value in cleaned.items():
        conn.execute(
            "INSERT INTO account_settings(account_id,key,value,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(account_id,key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (acct_id, key, str(value), time.time()))
    conn.commit()
    return cleaned


def reset(conn, acct_id):
    conn.execute("DELETE FROM account_settings WHERE account_id=?", (acct_id,))
    conn.commit()
