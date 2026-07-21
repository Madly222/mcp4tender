from __future__ import annotations

import hashlib
import json
import re
import unicodedata


def _fold(value):
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return s.strip()


def dedup_key(title, buyer):
    t = _fold(title)
    b = _fold(buyer)
    if not t or not b:
        return None
    return t + "|" + b


def site_token(site):
    return site.get("id") or hashlib.sha1(
        (site.get("url") or "").encode("utf-8")).hexdigest()[:8]


def token_of(source, external_id):
    if source == "genericweb":
        ext = str(external_id or "")
        return ext.split(":", 1)[0] if ":" in ext else None
    return source or None


def rank_of(store, source, external_id):
    order = store.get("sources.rank", []) or []
    token = token_of(source, external_id)
    if not token:
        return len(order) + 1
    try:
        return order.index(token)
    except ValueError:
        return len(order) + 1


def carry_closed(incoming, stored_json):
    try:
        stored = json.loads(stored_json) if isinstance(stored_json, str) else (stored_json or {})
    except Exception:
        stored = {}
    if not isinstance(stored, dict):
        return incoming
    out = dict(incoming)
    if stored.get("awarded") and not out.get("awarded"):
        out["awarded"] = stored["awarded"]
    for key in ("status", "status_details"):
        if stored.get(key) and not out.get(key):
            out[key] = stored[key]
    return out
