from __future__ import annotations

from engine import user_settings
from workflows.segments import partition

_RELEVANT = (
    "SELECT t.id, t.normalized_json, t.origin, t.created_at, "
    "av.verdict av_verdict, tv.verdict tv_verdict "
    "FROM tenders t "
    "LEFT JOIN verdicts av ON av.tender_id=t.id AND av.stage_name='applicability' "
    "LEFT JOIN verdicts tv ON tv.tender_id=t.id AND tv.stage_name='triage' "
    "WHERE av.verdict IN ('can','partial') "
    "OR (av.verdict IS NULL AND tv.verdict='relevant') LIMIT 3000")


def segment_counts(conn, store, acct_id=0):
    rows = conn.execute(_RELEVANT).fetchall()
    buckets = partition(rows, user_settings.view(conn, store, acct_id))
    return {s: len(v) for s, v in buckets.items()}


def nav_counts(conn, store, acct_id=0):
    from workflows import work
    try:
        seg = segment_counts(conn, store, acct_id)
        decided = work.decided_ids(conn, acct_id)
        w = work.counts(conn, acct_id)
    except Exception:
        return {}
    view = user_settings.view(conn, store, acct_id)
    fresh = [r for r in partition(conn.execute(_RELEVANT).fetchall(), view)["new"]
             if r["id"] not in decided]
    out = {"inbox": len(fresh)}
    out.update({k: v for k, v in w.items() if v})
    return out
