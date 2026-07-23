from __future__ import annotations

import json
import time

from engine.collectors import CollectedItem, _store_item
from engine.dateparse import day_end_ts
from engine.hashing import content_hash
from engine.llm import LLMGateway
from workflows.collectors.genericweb import _html_to_text

_SCOPE = (
    "SELECT t.id, t.source, t.external_id, t.normalized_json "
    "FROM tenders t "
    "LEFT JOIN verdicts av ON av.tender_id=t.id AND av.stage_name='applicability' "
    "LEFT JOIN verdicts tv ON tv.tender_id=t.id AND tv.stage_name='triage' "
    "WHERE av.verdict IN ('can','partial') "
    "OR (av.verdict IS NULL AND tv.verdict='relevant') "
    "ORDER BY t.updated_at ASC LIMIT ?"
)

RECHECK_SYS = (
    "You re-check whether ONE public tender is still open for bids. Read the page text and "
    "reply with ONLY a JSON object and nothing else: "
    '{"status": "<stage label in the page\'s own words, or empty>", '
    '"deadline": "<YYYY-MM-DD submission deadline, or empty>", '
    '"cancelled": <true|false>, "awarded": <true|false>}. '
    "cancelled=true only if the page states the procedure was annulled/cancelled. "
    "awarded=true only if a winner or contract award is shown."
)


def _nj(row):
    v = row["normalized_json"]
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v or {}


def _url_of(nj):
    u = nj.get("url")
    return u if isinstance(u, str) and u.startswith(("http://", "https://")) else None


def _fetch_default(url):
    from engine.http import get_text
    return get_text(url, timeout=20, retries=1)


def _parse(text):
    try:
        s = text[text.index("{"):text.rindex("}") + 1]
        out = json.loads(s)
        return out if isinstance(out, dict) else None
    except Exception:
        return None


def _apply(nj, data):
    out = dict(nj)
    if data.get("cancelled"):
        out["status"] = "cancelled"
        out["status_details"] = str(data.get("status") or "cancelled")[:80]
    elif data.get("awarded"):
        out["awarded"] = True
        if data.get("status"):
            out["status_details"] = str(data["status"])[:80]
    elif data.get("status"):
        out["status_details"] = str(data["status"])[:80]
    if data.get("deadline"):
        out["deadline"] = str(data["deadline"])[:32]
    return out


def _closed(nj, now=None):
    if str(nj.get("status") or "").lower() == "cancelled":
        return True
    if nj.get("awarded"):
        return True
    ts = day_end_ts(nj.get("deadline"))
    if ts is not None and ts < (now or time.time()):
        return True
    return False


def recheck_one(store, conn, row, fetch, gw):
    nj = _nj(row)
    if _closed(nj):
        return "closed"
    url = _url_of(nj)
    if not url:
        return "skip"
    try:
        page = fetch(url)
    except Exception:
        return "error"
    if not page:
        return "error"
    text = _html_to_text(str(page), url, 20000)
    phash = content_hash(text)
    seen = conn.execute("SELECT content_hash FROM recheck_state WHERE tender_id=?",
                        (row["id"],)).fetchone()
    if seen and seen["content_hash"] == phash:
        return "unchanged"
    resp = gw.complete("extract", RECHECK_SYS,
                       [{"role": "user", "content": text}], max_tokens=200)
    data = _parse(resp.get("text", "")) or {}
    changed = _apply(nj, data)
    item = CollectedItem(external_id=row["external_id"], raw={"recheck": True, "url": url},
                         normalized=changed)
    _store_item(conn, row["source"], item, "recheck", store)
    conn.execute(
        "INSERT INTO recheck_state(tender_id, content_hash, checked_at) VALUES(?,?,?) "
        "ON CONFLICT(tender_id) DO UPDATE SET content_hash=excluded.content_hash, "
        "checked_at=excluded.checked_at",
        (row["id"], phash, int(time.time())))
    conn.commit()
    return "checked"


def run_recheck(store, conn, fetch=None, gw=None, limit=200, logger=lambda m: None):
    fetch = fetch or _fetch_default
    gw = gw or LLMGateway(store, conn)
    rows = conn.execute(_SCOPE, (limit,)).fetchall()
    stats = {"checked": 0, "unchanged": 0, "skip": 0, "error": 0, "closed": 0}
    for r in rows:
        res = recheck_one(store, conn, r, fetch, gw)
        stats[res] = stats.get(res, 0) + 1
        logger(f"recheck {r['id']}: {res}")
    return stats
